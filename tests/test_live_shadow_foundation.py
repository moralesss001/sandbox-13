import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from src.binance_shadow_data import DataUnavailable
from src.live_paper_storage import ShadowJournal
from src.live_shadow import LiveShadowEngine, new_snapshot, run_shadow_command
from src.shadow_execution import number


class Feed:
    def __init__(self):
        self.now = 1000000
        self.rows = [self.trade(10, self.now)]
        self.fail = False
        self.gap = False
        self.events = []

    @staticmethod
    def trade(identifier, stamp):
        return dict(a=identifier, p="100", q="1", T=stamp, f=identifier, l=identifier, m=False)

    def trades(self, symbol, from_id=None, limit=1000):
        if self.fail:
            raise DataUnavailable("simulated disconnect")
        if from_id is None:
            return self.rows[-limit:]
        rows = [row for row in self.rows if row["a"] >= from_id]
        return rows[-1:] if self.gap else rows[:limit]

    def quote(self, symbol):
        return dict(symbol=symbol, time=self.now, bidPrice="100", askPrice="101", bidQty="5", askQty="5")

    def funding(self, symbol, start_ms, end_ms):
        return [e for e in self.events if start_ms <= e["fundingTime"] <= end_ms]

    def server_time(self):
        return self.now


def engine_at(root, feed=None):
    return LiveShadowEngine(root, metadata=new_snapshot(["BTCUSDT"]), client=feed or Feed())


def signal(engine, name="synthetic", stamp=1000000):
    return engine.execution.record_signal(name, "BTCUSDT", "LONG", "1", stamp,
                                          {"as_of_ms": stamp - 1, "values": {"synthetic": True}})


def test_durable_signal_context_before_quote_fill(tmp_path):
    feed = Feed()
    engine = engine_at(tmp_path, feed)
    try:
        engine.poll_once()
        signal(engine)
        with pytest.raises(ValueError, match="post-signal"):
            engine.execution.enter("synthetic", feed.now)
        feed.now += 100
        engine.poll_once()
        assert engine.execution.enter("synthetic", feed.now)
        assert not engine.execution.enter("synthetic", feed.now + 1)
        events = engine.journal.db.execute("SELECT kind FROM events ORDER BY seq").fetchall()
        assert events.index(("signal_context",)) < events.index(("model_entry",))
        state = engine.journal.read()
        assert state["signals"]["synthetic"]["context"]["as_of_ms"] < state["positions"]["synthetic"]["entry_ms"]
        assert state["positions"]["synthetic"]["exchange_fill"] is False
    finally:
        engine.close()


def test_disconnect_gap_bounded_recovery_and_no_duplicates(tmp_path):
    feed = Feed()
    engine = engine_at(tmp_path, feed)
    try:
        engine.poll_once()
        signal(engine)
        feed.fail = True
        assert not engine.poll_once()["BTCUSDT"]["ready"]
        with pytest.raises(ValueError, match="blocked"):
            engine.execution.enter("synthetic", feed.now)
        feed.fail = False
        feed.now += 100
        feed.rows.extend(Feed.trade(i, feed.now) for i in range(11, 15))
        feed.gap = True
        assert not engine.poll_once()["BTCUSDT"]["ready"]
        assert engine.journal.read()["market"]["BTCUSDT"]["last_id"] == 10
        feed.gap = False
        assert engine.poll_once()["BTCUSDT"]["ready"]
        engine.poll_once()
        rows = engine.journal.db.execute("SELECT payload FROM events WHERE kind='public_trades'").fetchall()
        ids = [t["a"] for r in rows for t in json.loads(r[0])["rows"]]
        assert ids == list(range(10, 15))
        engine.execution.enter("synthetic", feed.now)
    finally:
        engine.close()


def test_funding_accounting_late_publication_and_replay(tmp_path):
    feed = Feed()
    engine = engine_at(tmp_path, feed)
    try:
        engine.poll_once()
        signal(engine)
        feed.now += 100
        engine.poll_once()
        engine.execution.enter("synthetic", feed.now)
        entry_ms = feed.now
        feed.now += 200
        engine.poll_once()
        engine.execution.exit("synthetic", feed.now)
        event = dict(symbol="BTCUSDT", fundingTime=entry_ms + 50, fundingRate="0.001", markPrice="102")
        assert engine.execution.funding(event)
        assert not engine.execution.funding(event)
        state = engine.journal.read()
        p = state["closed"]["synthetic"]
        assert number(p["entry_price"]) == number("101.0505")
        assert number(p["exit_price"]) == number("99.9500")
        assert number(p["funding"]) == number("-0.102")
        expected = number(p["exit_price"]) - number(p["entry_price"]) - number(p["entry_fee"]) - number(p["exit_fee"]) - number("0.102")
        assert number(p["net_pnl"]) == expected
        assert number(state["balance"]) == 1000 + expected
        assert number(engine.execution.accounting()["quote_equity_usdt"]) == number(state["balance"])
        # Same-timestamp entry is not charged; previous quantity owns that funding.
        engine.execution.funding(dict(event, fundingTime=entry_ms))
        assert engine.journal.read()["balance"] == state["balance"]
    finally:
        engine.close()


def restart_worker(root, phase):
    feed = Feed()
    if phase == "second":
        feed.now += 200
        feed.rows.extend(Feed.trade(i, feed.now) for i in range(11, 14))
    engine = engine_at(root, feed)
    try:
        if phase == "first":
            engine.poll_once()
            signal(engine)
            feed.now += 100
            engine.poll_once()
            engine.execution.enter("synthetic", feed.now)
        else:
            assert len(engine.journal.read()["positions"]) == 1
            assert not engine.journal.read()["health"]["BTCUSDT"]["ready"]
            engine.poll_once()
            assert not signal(engine)
            assert not engine.execution.enter("synthetic", feed.now)
            engine.execution.exit("synthetic", feed.now)
            assert not engine.execution.exit("synthetic", feed.now + 1)
    finally:
        engine.close()


def test_real_process_restart_preserves_position_and_deduplicates(tmp_path):
    command = "import runpy,sys; runpy.run_path(sys.argv[1])['restart_worker'](sys.argv[2],sys.argv[3])"
    for phase in ("first", "second"):
        result = subprocess.run([sys.executable, "-B", "-c", command, str(Path(__file__).resolve()), str(tmp_path), phase],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    db = sqlite3.connect(str(tmp_path / "shadow.sqlite3"))
    try:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        state = json.loads(db.execute("SELECT body FROM state").fetchone()[0])
        assert not state["positions"] and len(state["closed"]) == 1
        assert state["closed"]["synthetic"]["gap_exposure"]
        for kind in ("signal_context", "model_entry", "model_exit"):
            assert db.execute("SELECT COUNT(*) FROM events WHERE kind=?", (kind,)).fetchone()[0] == 1
        rows = db.execute("SELECT payload FROM events WHERE kind='public_trades'").fetchall()
        assert [r["a"] for row in rows for r in json.loads(row[0])["rows"]] == [10, 11, 12, 13]
    finally:
        db.close()


def test_transaction_failure_does_not_advance_checkpoint(tmp_path):
    journal = ShadowJournal(tmp_path / "s.sqlite3", new_snapshot(["BTCUSDT"]))
    try:
        before = journal.read()
        def failure(state):
            state["market"]["BTCUSDT"] = {"last_id": 99}
            raise OSError(28, "synthetic ENOSPC")
        with pytest.raises(OSError):
            journal.transact("broken", "trades", {}, failure)
        assert journal.read() == before
        assert journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    finally:
        journal.close()


def test_fatal_storage_not_swallowed_as_symbol_failure(tmp_path, monkeypatch):
    engine = engine_at(tmp_path)
    try:
        def fail(*args, **kwargs):
            raise OSError(28, "synthetic storage full")
        monkeypatch.setattr(engine, "_append_trades", fail)
        with pytest.raises(OSError):
            engine.poll_once()
        assert not engine.journal.read()["health"]["BTCUSDT"]["ready"]
    finally:
        engine.close()


def test_invalid_context_duplicate_and_stale_quote_fail_closed(tmp_path):
    engine = engine_at(tmp_path)
    try:
        engine.poll_once()
        signal(engine)
        with pytest.raises(ValueError, match="context"):
            engine.execution.record_signal("bad", "BTCUSDT", "LONG", "1", 1, {"as_of_ms": 2})
        with pytest.raises(ValueError, match="conflicting"):
            signal(engine, stamp=999999)
        with pytest.raises(ValueError, match="stale"):
            engine.execution.enter("synthetic", 1006000)
        with pytest.raises(BlockingIOError):
            engine_at(tmp_path)
    finally:
        engine.close()


def test_new_cli_refuses_existing_data(tmp_path):
    (tmp_path / "existing").write_text("preserve")
    with pytest.raises(ValueError, match="empty"):
        run_shadow_command(tmp_path, ["BTCUSDT"])
    assert (tmp_path / "existing").read_text() == "preserve"


def test_shared_quote_liquidity_and_backdated_fill(tmp_path):
    feed = Feed()
    engine = engine_at(tmp_path, feed)
    try:
        engine.poll_once()
        for name in ("one", "two"):
            engine.execution.record_signal(name, "BTCUSDT", "LONG", "4", feed.now,
                                           {"as_of_ms": feed.now, "values": {}})
        feed.now += 100
        engine.poll_once()
        engine.execution.funding(dict(symbol="BTCUSDT", fundingTime=feed.now + 1,
                                      fundingRate="0.001", markPrice="100"))
        with pytest.raises(ValueError, match="backdated"):
            engine.execution.enter("one", feed.now)
        engine.execution.enter("one", feed.now + 1)
        with pytest.raises(ValueError, match="remaining"):
            engine.execution.enter("two", feed.now + 1)
        assert len(engine.journal.read()["positions"]) == 1
    finally:
        engine.close()


def test_late_funding_older_than_one_day_is_reconciled(tmp_path):
    feed = Feed()
    engine = engine_at(tmp_path, feed)
    try:
        engine.poll_once()
        signal(engine)
        feed.now += 100
        engine.poll_once()
        engine.execution.enter("synthetic", feed.now)
        event_time = feed.now + 100
        feed.now += 3 * 86400000
        engine.poll_once()
        feed.events = [dict(symbol="BTCUSDT", fundingTime=event_time,
                            fundingRate="0.001", markPrice="100")]
        engine.poll_once()
        assert engine.journal.read()["positions"]["synthetic"]["funding"] == "-0.100"
    finally:
        engine.close()


def test_shadow_fatal_finalization_reads_shadow_not_legacy(tmp_path):
    from src.live_shadow import finalize_shadow_failure
    from src.research_session_manager import ResearchSessionManager

    manager = ResearchSessionManager(tmp_path)
    manager.ensure_initialized()
    sid, paths = manager.create_session(new_snapshot(["BTCUSDT"]))
    manager.mark_start_requested(sid)
    feed = Feed()
    engine = LiveShadowEngine(paths.root, client=feed)
    engine.poll_once()
    signal(engine)
    feed.now += 100
    engine.poll_once()
    engine.execution.enter("synthetic", feed.now)
    engine.close()
    finalize_shadow_failure(manager, sid, "synthetic_constructor_failure")
    assert manager.global_status_store.read()["unresolved_open_positions_count"] == 1
    assert manager.global_status_store.read()["control_state"] == "stopped"
    assert paths.open_positions.read_text().strip() == "[]"


def test_shadow_unreadable_ledger_count_is_unknown(tmp_path):
    from src.live_shadow import finalize_shadow_failure
    from src.research_session_manager import ResearchSessionManager

    manager = ResearchSessionManager(tmp_path)
    manager.ensure_initialized()
    sid, paths = manager.create_session(new_snapshot(["BTCUSDT"]))
    finalize_shadow_failure(manager, sid, "missing_ledger")
    state = manager.global_status_store.read()
    assert state["unresolved_open_positions_count"] is None
    assert state["shadow_accounting_status"] == "UNKNOWN"
    assert state["control_state"] == "stopped"
    assert state["active_session_id"] == sid


def test_stop_request_is_not_overwritten(tmp_path):
    class RacingStatus:
        def __init__(self):
            self.reads = 0
            self.state = {"control_state": "start_requested"}
        def read(self):
            self.reads += 1
            if self.reads == 2:
                self.state["control_state"] = "stop_requested"
            return dict(self.state)
        def update(self, **values):
            self.state.update(values)

    engine = engine_at(tmp_path)
    status = RacingStatus()
    engine.status_store = status
    engine.poll_once = lambda: pytest.fail("must not poll after pending stop")
    engine.run()
    assert status.state["control_state"] == "stop_requested"


def test_sqlite_full_during_commit_is_atomic(tmp_path):
    journal = ShadowJournal(tmp_path / "s.sqlite3", new_snapshot(["BTCUSDT"]))
    try:
        before = journal.read()
        pages = journal.db.execute("PRAGMA page_count").fetchone()[0]
        journal.db.execute("PRAGMA max_page_count=" + str(pages))
        with pytest.raises(sqlite3.OperationalError, match="full"):
            journal.transact("oversize", "test", {"blob": "x" * 1000000},
                             lambda state: state.update(balance="999"))
        assert journal.read() == before
        assert journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert journal.db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        journal.close()


def live_technical_worker(root, phase):
    """Explicitly invoked bounded technical smoke, never collected as a test."""
    from src.binance_shadow_data import PublicShadowClient
    from src.research_session_manager import ResearchSessionManager

    manager = ResearchSessionManager(root)
    if phase == "first":
        if Path(root).exists() and any(Path(root).iterdir()):
            raise ValueError("smoke requires new data")
        manager.ensure_initialized()
        sid, paths = manager.create_session(new_snapshot(["BTCUSDT"]))
        manager.mark_start_requested(sid)
    else:
        status = manager.global_status_store.read()
        sid = status["active_session_id"]
        paths = manager.paths(sid)
    client = PublicShadowClient(timeout=5, max_pages=5)
    engine = LiveShadowEngine(paths.root, client=client, session_id=sid,
                              session_manager=manager, status_store=manager.global_status_store)
    try:
        if phase == "first":
            assert engine.poll_once()["BTCUSDT"]["ready"]
            stamp = client.server_time()
            engine.execution.record_signal("technical-only-001", "BTCUSDT", "LONG", "0.001",
                                           stamp, {"as_of_ms": stamp, "values": {"synthetic": True}})
            assert engine.poll_once()["BTCUSDT"]["ready"]
            engine.execution.enter("technical-only-001", client.server_time())
            class Disconnected:
                def trades(self, *args, **kwargs):
                    raise DataUnavailable("technical_artificial_disconnect")
            engine.client = Disconnected()
            assert not engine.poll_once()["BTCUSDT"]["ready"]
            engine.publish_status()
        else:
            state = engine.journal.read()
            assert len(state["positions"]) == 1
            assert not state["health"]["BTCUSDT"]["ready"]
            assert engine.poll_once()["BTCUSDT"]["ready"]
            assert not engine.execution.enter("technical-only-001", client.server_time())
            engine.execution.exit("technical-only-001", client.server_time())
            assert not engine.execution.exit("technical-only-001", client.server_time())
            engine.invalidate("stopped")
            engine.publish_status()
            manager.finalize_session(sid, stop_reason="technical_validation_complete",
                                     unresolved_open_positions_count=0, latest_report_path=None)
        state = engine.journal.read()
        print(json.dumps({"phase": phase, "session_id": sid, "signals": len(state["signals"]),
                          "positions": len(state["positions"]), "closed": len(state["closed"]),
                          "health": state["health"], "checkpoint": state["market"]["BTCUSDT"]["last_id"],
                          "integrity": engine.journal.db.execute("PRAGMA integrity_check").fetchone()[0],
                          "safety": state["metadata"]["safety"]}, sort_keys=True))
    finally:
        engine.close()


def test_gap_in_other_symbol_blocks_new_entry(tmp_path):
    feed = Feed()
    engine = LiveShadowEngine(tmp_path, metadata=new_snapshot(["BTCUSDT", "ETHUSDT"]), client=feed)
    try:
        engine.poll_once()
        signal(engine)
        feed.now += 100
        engine.poll_once()
        engine.invalidate("missing ETH", symbol="ETHUSDT", gap=True)
        with pytest.raises(ValueError, match="incomplete session"):
            engine.execution.enter("synthetic", feed.now)
    finally:
        engine.close()


def test_short_model_and_funding_sign(tmp_path):
    feed = Feed()
    engine = engine_at(tmp_path, feed)
    try:
        engine.poll_once()
        engine.execution.record_signal("short", "BTCUSDT", "SHORT", "1", feed.now,
                                       {"as_of_ms": feed.now, "values": {}})
        feed.now += 100
        engine.poll_once()
        engine.execution.enter("short", feed.now)
        engine.execution.funding(dict(symbol="BTCUSDT", fundingTime=feed.now + 1,
                                      fundingRate="0.001", markPrice="100"))
        feed.now += 100
        engine.poll_once()
        engine.execution.exit("short", feed.now)
        state = engine.journal.read()
        position = state["closed"]["short"]
        assert number(position["funding"]) == number("0.100")
        expected = number("99.95") - number("101.0505") - number(position["entry_fee"]) - number(position["exit_fee"]) + number("0.1")
        assert number(position["net_pnl"]) == expected
        assert number(state["balance"]) == 1000 + expected
    finally:
        engine.close()


def test_supervisor_corrupt_snapshot_keeps_shadow_position_count(tmp_path, monkeypatch):
    import time
    from src.research_session_manager import ResearchSessionManager
    from src.run_all import RunAllConfig, run_all

    manager = ResearchSessionManager(tmp_path)
    manager.ensure_initialized()
    sid, paths = manager.create_session(new_snapshot(["BTCUSDT"]))
    manager.mark_start_requested(sid)
    feed = Feed()
    engine = LiveShadowEngine(paths.root, client=feed)
    engine.poll_once()
    signal(engine)
    feed.now += 100
    engine.poll_once()
    engine.execution.enter("synthetic", feed.now)
    engine.close()
    paths.config_snapshot.write_text("{broken")
    monkeypatch.setattr("src.run_all.install_shutdown_handlers", lambda *args: None)
    config = RunAllConfig(symbols=["BTCUSDT"], timeframe="15m",
                          candidate_source="production_like_raw", interval_sec=1,
                          data_root=str(tmp_path))
    run_all(config=config, telegram_runner=lambda **kwargs: time.sleep(0.05),
            supervisor_runtime_sec=0.2)
    state = manager.global_status_store.read()
    assert state["control_state"] == "stopped"
    assert state["unresolved_open_positions_count"] == 1
    assert not state["active_session_id"]
    db = sqlite3.connect(str(paths.root / "shadow.sqlite3"))
    try:
        assert len(json.loads(db.execute("SELECT body FROM state").fetchone()[0])["positions"]) == 1
    finally:
        db.close()
