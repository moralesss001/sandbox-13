"""Offline contract tests for standard execution, independent of legacy signals."""
from decimal import Decimal as D
import hashlib
import socket

import pytest

from src.live_paper_storage import ShadowJournal
from src.live_shadow import legacy_snapshot
from src.shadow_execution import StandardShadowExecution


T = 1_000_000


class FakeMarket:
    """Publish already validated market state; no transport or live engine."""

    def __init__(self, journal):
        self.journal = journal
        self.seq = 0

    def publish(self, stamp, bid="100", ask="101", size="5", ready=True, gap=False):
        self.seq += 1
        quote = dict(symbol="BTCUSDT", time=stamp, bidPrice=bid,
                     askPrice=ask, bidQty=size, askQty=size)

        def apply(state):
            state["market"].setdefault("BTCUSDT", {}).update(quote=quote)
            state["health"]["BTCUSDT"] = {"ready": ready}
            if gap:
                for position in state["positions"].values():
                    position["gap_exposure"] = True

        self.journal.transact("fake:" + str(self.seq), "fake_market", quote, apply)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in standard execution tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def rig(tmp_path):
    metadata = legacy_snapshot()
    journal = ShadowJournal(tmp_path / "shadow.sqlite3", metadata)
    try:
        yield journal, StandardShadowExecution(journal), FakeMarket(journal)
    finally:
        journal.close()


def signal(execution, side="LONG", name="s", stamp=T):
    levels = dict(entry_reference="100", tp="110", sl="90")
    if side == "SHORT":
        levels.update(tp="90", sl="110")
    context = dict(as_of_ms=stamp - 1, source_levels=levels,
                   values={"synthetic": True})
    return execution.record_signal(name, "BTCUSDT", side, None, stamp, context)


def opened(rig, side="LONG"):
    journal, execution, market = rig
    assert signal(execution, side)
    market.publish(T + 1000)
    assert execution.enter("s", T + 1000)
    return journal.read()["positions"]["s"]


def assert_rejected(journal, operation, match):
    before = journal.read()
    count = journal.db.execute("SELECT COUNT(*) FROM events").fetchone()
    with pytest.raises(ValueError, match=match):
        operation()
    assert journal.read() == before
    assert journal.db.execute("SELECT COUNT(*) FROM events").fetchone() == count


@pytest.mark.parametrize("side,price", [("LONG", "101.0505"), ("SHORT", "99.9500")])
def test_fixed_notional_at_fill_and_durable_context(rig, side, price):
    journal, execution, market = rig
    metadata = journal.read()["metadata"]
    assert metadata["initial_balance"] == "1000"
    assert metadata["max_quote_age_ms"] == 5000
    assert metadata["execution_penalty"] == "0.0005"
    assert metadata["fee_rate"] == "0.0005"
    assert signal(execution, side)
    observer = ShadowJournal(journal.path, metadata)
    try:
        state = observer.read()
        record = state["signals"]["s"]
        assert record["context"]["source_levels"]["entry_reference"] == "100"
        assert record["quantity"] is None
        assert record["fixed_notional_usdt"] == "100"
        for field in ("rules_hash", "rules_version", "code_revision", "code_hash"):
            assert record[field] == metadata[field]
        assert not state["positions"]
        assert state["balance"] == "1000"
    finally:
        observer.close()
    market.publish(T + 1000)
    assert execution.enter("s", T + 1000)
    state = journal.read()
    position = state["positions"]["s"]
    assert D(position["entry_price"]) == D(price)
    assert D(position["quantity"]) == D(100) / D(price)
    assert D(position["quantity"]) != D(100) / D("100")
    assert state["signals"]["s"]["quantity"] is None
    assert D(position["entry_notional"]) == 100
    assert D(position["entry_fee"]) == D("0.05")
    assert D(state["balance"]) == D("999.95")
    assert position["exchange_fill"] is False
    assert position["execution_model"] == "STANDARD_SHADOW_EXECUTION"
    kinds = [row[0] for row in journal.db.execute("SELECT kind FROM events ORDER BY seq")]
    assert kinds.index("signal_context") < kinds.index("model_entry")


def test_legacy_snapshot_preserves_full_metadata_and_balance(rig):
    from src.legacy_crypto13_shadow import ARCHIVE_SHA256, SOURCE_SHA256, SYMBOLS

    journal, execution, market = rig
    metadata = journal.read()["metadata"]
    assert metadata["engine_mode"] == "legacy_crypto13_shadow_v1"
    assert metadata["candidate_source"] == "legacy_crypto13_auto"
    assert metadata["candidate_source_version"] == "legacy_auto_archive_v1"
    assert metadata["symbols"] == metadata["configured_symbols"] == list(SYMBOLS)
    assert len(metadata["symbols"]) == 46
    assert metadata["initial_balance"] == journal.read()["balance"] == "1000"
    rules = metadata["rules"]
    assert rules["initial_balance"] == "1000"
    assert rules["symbols"] == list(SYMBOLS)
    assert rules["execution"] == "STANDARD_SHADOW_EXECUTION"
    assert rules["archive_sha256"] == ARCHIVE_SHA256
    assert rules["source_sha256"] == SOURCE_SHA256
    for field, expected in dict(fixed_notional_usdt="100", latency_ms=1000,
                                fee_rate="0.0005", execution_penalty="0.0005",
                                max_quote_age_ms=5000, funding_poll_interval_ms=60000).items():
        assert metadata[field] == rules[field] == expected
    assert rules["leverage"] == 1
    assert metadata["rules_version"] == rules["version"]
    assert metadata["rules_hash"] == hashlib.sha256(ShadowJournal.encode(rules).encode()).hexdigest()
    assert len(metadata["code_hash"]) == 64
    assert metadata["code_revision"]
    assert metadata["safety"] == dict(paper_only=True, real_orders=False,
                                      testnet_orders=False, private_api=False, orders_sent=False)


@pytest.mark.parametrize("quantity", ["1", 1, "100", "0"])
def test_signal_rejects_decision_time_quantity(rig, quantity):
    journal, execution, market = rig
    context = dict(as_of_ms=T - 1,
                   source_levels=dict(entry_reference="100", tp="110", sl="90"))
    assert_rejected(journal, lambda: execution.record_signal(
        "s", "BTCUSDT", "LONG", quantity, T, context), "quantity.*only at fill")


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("entry,tp,sl", [
    ("100", "100", "90"), ("100", "110", "100"),
    ("100", "90", "110"), ("100", "110", "0"),
    ("100", "110", "-1"), ("0", "110", "90"),
    ("100", "0", "90"), ("NaN", "110", "90"),
    ("100", "Infinity", "90"), ("100", "110", "NaN"),
])
def test_signal_rejects_nonpositive_nonfinite_or_unordered_levels(rig, side, entry, tp, sl):
    journal, execution, market = rig
    if side == "SHORT":
        tp, sl = sl, tp
    context = dict(as_of_ms=T - 1,
                   source_levels=dict(entry_reference=entry, tp=tp, sl=sl))
    assert_rejected(journal, lambda: execution.record_signal(
        "s", "BTCUSDT", side, None, T, context), "source levels|non-finite")


@pytest.mark.parametrize("quote_offset,now_offset,allowed", [
    (999, 999, False), (999, 1000, False), (1000, 1000, True),
    (1000, 6000, True), (1000, 6001, False), (1001, 1000, False),
])
def test_entry_latency_and_quote_freshness(rig, quote_offset, now_offset, allowed):
    journal, execution, market = rig
    signal(execution)
    market.publish(T + quote_offset)
    if allowed:
        assert execution.enter("s", T + now_offset)
    else:
        assert_rejected(journal, lambda: execution.enter("s", T + now_offset),
                        "latency|stale/future")


def test_missing_market_blocks_then_same_signal_retries(rig):
    journal, execution, market = rig
    signal(execution)
    assert_rejected(journal, lambda: execution.enter("s", T + 1000), "blocked")
    market.publish(T + 1000, ready=False)
    assert_rejected(journal, lambda: execution.enter("s", T + 1000), "blocked")
    market.publish(T + 1001)
    assert execution.enter("s", T + 1001)
    assert not execution.enter("s", T + 1002)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_insufficient_book_size_is_atomic_and_retryable(rig, side):
    journal, execution, market = rig
    signal(execution, side)
    market.publish(T + 1000, size="0.01")
    assert_rejected(journal, lambda: execution.enter("s", T + 1000), "size")
    market.publish(T + 1001)
    assert execution.enter("s", T + 1001)


@pytest.mark.parametrize("side,trigger,bid,ask", [
    ("LONG", "TP", "110", "111"), ("LONG", "SL", "90", "91"),
    ("SHORT", "TP", "89", "90"), ("SHORT", "SL", "109", "110"),
])
def test_frozen_levels_exit_intent_and_delayed_fill(rig, side, trigger, bid, ask):
    journal, execution, market = rig
    position = opened(rig, side)
    assert_rejected(journal, lambda: execution.exit("s", T + 1500), "intent")
    # Opposite book side alone crossing a level is not executable-side touch.
    market.publish(T + 1500, bid="100", ask="111" if side == "LONG" else "100")
    if side == "SHORT":
        market.publish(T + 1501, bid="89", ask="100")
    assert not execution.request_exit("s", T + 1501)
    market.publish(T + 2000, bid=bid, ask=ask)
    assert execution.request_exit("s", T + 2000)
    intent = journal.read()["exit_intents"]["s"]
    assert intent["trigger"] == trigger
    assert intent["first_touch_verified"] is True
    assert journal.read()["positions"]["s"]["source_levels"] == position["source_levels"]
    assert_rejected(journal, lambda: execution.exit("s", T + 2999), "latency")
    assert_rejected(journal, lambda: execution.exit("s", T + 3000), "latency")
    market.publish(T + 3000, bid="99", ask="102")
    assert not execution.request_exit("s", T + 3000)
    assert journal.read()["exit_intents"]["s"] == intent
    assert execution.exit("s", T + 3000)
    closed = journal.read()["closed"]["s"]
    px = D("98.9505") if side == "LONG" else D("102.0510")
    qty = D(position["quantity"])
    gross = qty * (px - D(position["entry_price"])) * (1 if side == "LONG" else -1)
    fee = qty * px * D("0.0005")
    assert D(closed["exit_price"]) == px
    assert D(closed["exit_fee"]) == fee
    assert D(closed["gross_pnl"]) == gross
    assert D(closed["net_pnl"]) == gross - fee - D("0.05")
    assert D(journal.read()["balance"]) == D("999.95") + gross - fee


def test_gap_blocks_exit_then_recovery_keeps_first_touch_unverified(rig):
    journal, execution, market = rig
    opened(rig)
    market.publish(T + 2000, bid="110", ask="111", ready=False, gap=True)
    assert_rejected(journal, lambda: execution.request_exit("s", T + 2000), "blocked")
    market.publish(T + 4000, bid="110", ask="111")
    assert execution.request_exit("s", T + 4000)
    intent = journal.read()["exit_intents"]["s"]
    assert intent["decision_ms"] == T + 4000
    assert intent["trigger_quote"]["time"] == T + 4000
    assert intent["first_touch_verified"] is False
    market.publish(T + 5000, ready=False)
    assert_rejected(journal, lambda: execution.exit("s", T + 5000), "blocked")
    market.publish(T + 5001)
    assert execution.exit("s", T + 5001)
    assert journal.read()["closed"]["s"]["gap_exposure"] is True
    assert journal.read()["exit_intents"]["s"] == intent


@pytest.mark.parametrize("age,allowed", [(5000, True), (5001, False), (-1, False)])
def test_exit_quote_freshness_boundary(rig, age, allowed):
    journal, execution, market = rig
    opened(rig)
    market.publish(T + 2000, bid="110", ask="111")
    execution.request_exit("s", T + 2000)
    market.publish(T + 4000)
    if allowed:
        assert execution.exit("s", T + 4000 + age)
    else:
        assert_rejected(journal, lambda: execution.exit("s", T + 4000 + age),
                        "stale/future")


@pytest.mark.parametrize("mark", ["0", "-1", "NaN"])
def test_invalid_exact_funding_mark_is_rejected_atomically(rig, mark):
    journal, execution, market = rig
    opened(rig)
    event = dict(symbol="BTCUSDT", fundingTime=T + 1500,
                 fundingRate="0.001", markPrice=mark)
    assert_rejected(journal, lambda: execution.funding(event), "mark|non-finite")


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_exact_funding_uses_quantity_before_event_including_exit(rig, side):
    journal, execution, market = rig
    position = opened(rig, side)
    market.publish(T + 2000, bid="110", ask="111")
    execution.request_exit("s", T + 2000)
    market.publish(T + 3000)
    execution.exit("s", T + 3000)
    before = journal.read()
    amount = -D(position["quantity"]) * D("123.456") * D("0.00123") * (1 if side == "LONG" else -1)
    for offset, expected in [(1000, D(0)), (3000, amount), (3001, amount)]:
        event = dict(symbol="BTCUSDT", fundingTime=T + offset,
                     fundingRate="0.00123", markPrice="123.456")
        assert execution.funding(event)
        assert not execution.funding(event)
        state = journal.read()
        assert D(state["closed"]["s"]["funding"]) == expected
        assert D(state["balance"]) == D(before["balance"]) + expected
        assert D(state["closed"]["s"]["net_pnl"]) == D(before["closed"]["s"]["net_pnl"]) + expected


def test_restart_preserves_intent_and_deduplicates_all_operations(rig):
    journal, execution, market = rig
    opened(rig)
    market.publish(T + 2000, bid="110", ask="111")
    execution.request_exit("s", T + 2000)
    event = dict(symbol="BTCUSDT", fundingTime=T + 1500,
                 fundingRate="0.001", markPrice="102")
    execution.funding(event)
    metadata = journal.read()["metadata"]
    before = journal.read()
    journal.close()
    reopened = ShadowJournal(journal.path, metadata)
    try:
        retry = StandardShadowExecution(reopened)
        assert reopened.read() == before
        assert not signal(retry)
        assert not retry.enter("s", T + 2000)
        assert not retry.request_exit("s", T + 2000)
        assert not retry.funding(event)
        market.journal = reopened
        market.publish(T + 3000)
        assert retry.exit("s", T + 3000)
        closed = reopened.read()
        assert not retry.exit("s", T + 3001)
        assert not retry.enter("s", T + 3001)
        assert reopened.read() == closed
        for kind in ("signal_context", "model_entry", "model_exit_intent", "model_exit", "funding"):
            assert reopened.db.execute("SELECT COUNT(*) FROM events WHERE kind=?", (kind,)).fetchone() == (1,)
        assert reopened.db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        reopened.close()
    final = ShadowJournal(journal.path, metadata)
    try:
        retry = StandardShadowExecution(final)
        assert final.read() == closed
        assert not retry.exit("s", T + 4000)
        assert not retry.funding(event)
        assert not signal(retry)
        assert not retry.enter("s", T + 4000)
        assert final.read() == closed
    finally:
        final.close()
