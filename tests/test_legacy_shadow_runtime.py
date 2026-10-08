import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.live_shadow import LegacyShadowEngine, legacy_snapshot
from src.legacy_crypto13_shadow import SYMBOLS
from src.binance_shadow_data import DataUnavailable


class Adapter:
    def __init__(self):
        self.state = dict(last_sent={}, cooldown_until_ms=0)
        self.last_scan_report = {"evaluated": 46}

    def dump_state(self):
        return dict(self.state, last_sent=dict(self.state["last_sent"]))

    def restore_state(self, state):
        self.state = state

    def mark_sent(self, symbol, stamp):
        self.state["last_sent"][symbol] = stamp

    def finish_scan(self, sent):
        if sent:
            self.state["cooldown_until_ms"] = int(time.time() * 1000) + 120000

    def scan(self):
        return [candidate()]


def candidate():
    return dict(signal_id="BTCUSDT:1h:100:Long", symbol="BTCUSDT", direction="Long",
                entry=100, tp=110, sl=90, context={"as_of_ms": 1000000})


class Feed:
    def __init__(self, stamp=2000000):
        self.now = stamp
        self.last = 10
        self.fail = False
        self.skip = False
        self.price = 100

    def trades(self, symbol, from_id=None, limit=1000):
        if self.fail:
            raise DataUnavailable("synthetic gap")
        ids = [self.last] if from_id is None else list(range(from_id, self.last + 1))[:limit]
        if self.skip:
            ids = ids[1:]
        return [dict(a=i, p="100", q="1", T=self.now, f=i, l=i, m=False) for i in ids]

    def quote(self, symbol):
        return dict(symbol=symbol, time=self.now, bidPrice=str(self.price), askPrice=str(self.price + 1),
                    bidQty="10", askQty="10", lastUpdateId=self.now)

    def funding(self, *args):
        return []

    def server_time(self):
        return self.now


def engine(root, feed, adapter=None, metadata=None):
    return LegacyShadowEngine(root, metadata=metadata or legacy_snapshot(), client=feed, adapter=adapter or Adapter())


def record(execution, stamp=2000000):
    return execution.record_signal("technical", "BTCUSDT", "LONG", None, stamp,
        {"as_of_ms": stamp - 1, "source_levels": {"entry_reference": 100, "tp": 110, "sl": 90}})


def test_46_universe_and_execution_snapshot(tmp_path):
    snapshot = legacy_snapshot()
    assert snapshot["symbols"] == list(SYMBOLS)
    assert len(snapshot["symbols"]) == 46
    for key, value in (("latency_ms", 0), ("fixed_notional_usdt", "1000"), ("funding_poll_interval_ms", 0)):
        broken = dict(snapshot, **{key: value})
        with pytest.raises(ValueError, match="snapshot"):
            engine(tmp_path / key, Feed(), metadata=broken)
    with pytest.raises(ValueError, match="universe"):
        legacy_snapshot(["BTCUSDT"])


def test_signal_admission_restores_original_levels_and_dedup(tmp_path):
    e = engine(tmp_path, Feed())
    try:
        e._admit([candidate()])
        state = e.journal.read()
        s = state["signals"][candidate()["signal_id"]]
        assert s["quantity"] is None and s["fixed_notional_usdt"] == "100"
        assert s["context"]["source_levels"] == dict(entry_reference=100, tp=110, sl=90)
        assert s["context"]["source_signal"]["entry"] == 100
        assert not state["positions"]
        stamp = s["context"]["admission_local_ms"]
    finally:
        e.close()
    e = engine(tmp_path, Feed())
    try:
        assert e.adapter.dump_state()["last_sent"]["BTCUSDT"] == stamp
        e._admit([candidate()])
        assert len(e.journal.read()["signals"]) == 1
    finally:
        e.close()


def restart_worker(root, phase):
    feed = Feed()
    if phase == "second":
        feed.now += 3000
        feed.last = 13
    e = engine(root, feed)
    try:
        if phase == "first":
            e.poll_once(symbols=["BTCUSDT"])
            record(e.execution)
            feed.now += 1000
            e.poll_once(symbols=["BTCUSDT"])
            e.execution.enter("technical", feed.now)
        else:
            assert len(e.journal.read()["positions"]) == 1
            with pytest.raises(ValueError, match="incomplete"):
                e.execution.request_exit("technical", feed.now)
            feed.fail = True
            e.poll_once(symbols=["BTCUSDT"])
            assert not e.journal.read()["health"]["BTCUSDT"]["ready"]
            feed.fail = False
            feed.skip = True
            e.poll_once(symbols=["BTCUSDT"])
            assert not e.journal.read()["health"]["BTCUSDT"]["ready"]
            feed.skip = False
            e.poll_once(symbols=["BTCUSDT"])
            assert e.journal.read()["market"]["BTCUSDT"]["last_id"] == 13
            assert not record(e.execution)
            assert not e.execution.enter("technical", feed.now)
            feed.price = 110
            e.poll_once(symbols=["BTCUSDT"])
            e.execution.request_exit("technical", feed.now)
            with pytest.raises(ValueError, match="latency"):
                e.execution.exit("technical", feed.now)
            feed.now += 1000
            e.poll_once(symbols=["BTCUSDT"])
            e.execution.exit("technical", feed.now)
            assert not e.execution.exit("technical", feed.now)
            state = e.journal.read()
            assert not state["exit_intents"]["technical"]["first_touch_verified"]
            assert len(state["closed"]) == 1 and not state["positions"]
            rows = e.journal.db.execute("SELECT payload FROM events WHERE kind='public_trades'").fetchall()
            ids = [r["a"] for row in rows for r in json.loads(row[0])["rows"]]
            assert ids == list(range(10, 14))
            assert e.journal.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        e.close()


def test_real_process_restart_gap_and_exactly_once(tmp_path):
    code = "import runpy,sys; runpy.run_path(sys.argv[1])['restart_worker'](sys.argv[2],sys.argv[3])"
    for phase in ("first", "second"):
        result = subprocess.run([sys.executable, "-B", "-c", code, str(Path(__file__).resolve()), str(tmp_path), phase],
                                text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr


def test_cli_explicit_new_mode_only():
    from src.main import _build_parser

    args = _build_parser().parse_args(["legacy-shadow", "--data-root", "isolated"])
    assert not args.run_forever and args.max_iterations == 1


def test_crash_during_admission_resumes_batch_and_cooldown(tmp_path):
    e = engine(tmp_path, Feed())
    original = e.execution.record_signal
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("lost acknowledgement before cooldown checkpoint")
    e.execution.record_signal = crash
    with pytest.raises(RuntimeError, match="acknowledgement"):
        e._admit([candidate()])
    assert len(e.journal.read()["signals"]) == 1
    assert "legacy_admission" in e.journal.read()
    e.close()
    e = engine(tmp_path, Feed())
    try:
        e._admit(e.journal.read()["legacy_admission"]["selected"])
        state = e.journal.read()
        assert len(state["signals"]) == 1
        assert "legacy_admission" not in state
        assert state["legacy_adapter"]["cooldown_until_ms"] >= int(time.time() * 1000) + 119000
    finally:
        e.close()


def test_stop_prevents_admission(tmp_path):
    e = engine(tmp_path, Feed())
    try:
        e.stop_requested = True
        e._admit([candidate()])
        assert not e.journal.read()["signals"]
    finally:
        e.close()


def test_clock_skew_and_server_time_failure_fail_closed(tmp_path):
    feed = Feed()
    e = engine(tmp_path, feed)
    try:
        e.poll_once(symbols=["BTCUSDT"])
        e._advance_symbol("BTCUSDT")
        assert e.journal.read()["health"]["BTCUSDT"]["reason"] == "local_exchange_clock_skew"
        e.poll_once(symbols=["BTCUSDT"])
        def fail():
            raise DataUnavailable("temporary clock outage")
        feed.server_time = fail
        e._advance_symbol("BTCUSDT")
        assert not e.journal.read()["health"]["BTCUSDT"]["ready"]
    finally:
        e.close()


@pytest.mark.parametrize("offset_ms", [-900, 900])
def test_admission_uses_exchange_clock_not_local_skew(tmp_path, monkeypatch, offset_ms):
    feed = Feed()
    monkeypatch.setattr("src.live_shadow.time.time", lambda: (feed.now + offset_ms) / 1000)
    monkeypatch.setattr("src.live_shadow.time.sleep", lambda _: None)
    e = engine(tmp_path, feed)
    try:
        e._admit([candidate()])
        signal_id = candidate()["signal_id"]
        assert e.journal.read()["signals"][signal_id]["decision_ms"] == feed.now
        feed.now += 100
        e.poll_once(symbols=["BTCUSDT"])
        with pytest.raises(ValueError, match="latency"):
            e.execution.enter(signal_id, feed.now)
        feed.now += 900
        e.poll_once(symbols=["BTCUSDT"])
        assert e.execution.enter(signal_id, feed.now)
    finally:
        e.close()


def public_technical_worker(root, phase):
    """Explicit bounded public test, not collected by pytest and never a strategy."""
    from src.binance_shadow_data import PublicShadowClient
    from src.shadow_execution import number

    client = PublicShadowClient(timeout=5)
    metadata = dict(legacy_snapshot(), technical_validation=True)
    e = LegacyShadowEngine(root, metadata=metadata, client=client, adapter=Adapter())
    try:
        if phase == "first":
            e.poll_once(symbols=["BTCUSDT"])
            state = e.journal.read()
            assert state["health"]["BTCUSDT"]["ready"], state["health"]
            quote = state["market"]["BTCUSDT"]["quote"]
            bid = number(quote["bidPrice"])
            stamp = client.server_time()
            assert abs(stamp - int(time.time() * 1000)) < 1000, "local/public clock skew"
            # Deliberately synthetic levels cause a prompt technical exit; no legacy signal.
            levels = dict(entry_reference=str(bid * number("0.99")),
                          tp=str(bid * number("0.995")), sl=str(bid * number("0.98")))
            e.execution.record_signal("public-technical-only", "BTCUSDT", "LONG", None,
                                      stamp, {"as_of_ms": stamp, "source_levels": levels, "synthetic": True})
            for _ in range(8):
                time.sleep(1)
                e.poll_once(symbols=["BTCUSDT"])
                try:
                    e.execution.enter("public-technical-only", client.server_time())
                    break
                except ValueError:
                    continue
            state = e.journal.read()
            assert len(state["positions"]) == 1
            position = state["positions"]["public-technical-only"]
            assert int(position["entry_quote"]["time"]) >= stamp + 1000
            assert position["entry_notional"] == "100"
        elif phase == "second":
            assert len(e.journal.read()["positions"]) == 1
            assert not e.journal.read()["health"]["BTCUSDT"]["ready"]
            original = client.trades
            def disconnect(*args, **kwargs):
                raise DataUnavailable("artificial public smoke disconnect")
            client.trades = disconnect
            e.poll_once(symbols=["BTCUSDT"])
            assert not e.journal.read()["health"]["BTCUSDT"]["ready"]
            client.trades = original
            for _ in range(10):
                time.sleep(1)
                e.poll_once(symbols=["BTCUSDT"])
                try:
                    now = client.server_time()
                    e.execution.request_exit("public-technical-only", now)
                    e.execution.exit("public-technical-only", now)
                    break
                except ValueError:
                    continue
            state = e.journal.read()
            assert len(state["closed"]) == 1 and not state["positions"]
            assert not e.execution.enter("public-technical-only", client.server_time())
            rows = e.journal.db.execute("SELECT payload FROM events WHERE kind='public_trades'").fetchall()
            ids = [r["a"] for row in rows for r in json.loads(row[0])["rows"]]
            assert ids == list(range(ids[0], ids[-1] + 1))
            closed = state["closed"]["public-technical-only"]
            expected = (number(closed["gross_pnl"]) - number(closed["entry_fee"])
                        - number(closed["exit_fee"]) + number(closed["funding"]))
            assert number(closed["net_pnl"]) == expected
            assert e.journal.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        else:
            raise ValueError("unknown technical phase")
        print(json.dumps(dict(phase=phase, status="PASS", signals=len(state["signals"]),
                              open=len(state["positions"]), closed=len(state["closed"]),
                              journal=str(e.journal.path), safety=metadata["safety"])))
    finally:
        e.close()
