import pandas as pd

from src.candidate_sources import PRODUCTION_LIKE_RAW_METADATA, SIMPLIFIED_PLACEHOLDER_METADATA
from src.hypothesis_registry import HypothesisRegistry
from src.live_paper_storage import LivePaperStorage
from src.live_research_engine import LiveResearchEngine
from src.order_models import SignalCandidate
from src.paper_broker import PaperBroker
from src.portfolio import PaperPortfolio
from src.runtime_status import RuntimeStatusStore
from src.shadow_gates import attach_shadow_gate_metadata


def _klines(close_time: int = 1_700_000_000_000, high: float = 101.0, low: float = 99.0) -> pd.DataFrame:
    rows = []
    for index in range(20):
        close = 100.0
        rows.append(
            {
                "open_time": close_time - (20 - index) * 900_000,
                "open": close,
                "high": high if index == 19 else close + 0.5,
                "low": low if index == 19 else close - 0.5,
                "close": close,
                "volume": 1,
                "close_time": close_time + index,
                "quote_asset_volume": 1,
                "number_of_trades": 1,
                "taker_buy_base_volume": 1,
                "taker_buy_quote_volume": 1,
                "ignore": 0,
            }
        )
    return pd.DataFrame(rows)


def _signal(direction: str = "LONG", rsi: float = 50.0, raw=None) -> SignalCandidate:
    return attach_shadow_gate_metadata(SignalCandidate(
        symbol="BTCUSDT",
        timeframe="15m",
        direction=direction,
        entry=100.0,
        tp=110.0,
        sl=95.0,
        rr_ratio=2.0,
        rsi=rsi,
        atr_pct=0.01,
        market_phase="trend",
        session="US",
        setup_type="continuation",
        trend_htf="Long",
        signal_source="test_live_paper",
        **SIMPLIFIED_PLACEHOLDER_METADATA.as_candidate_kwargs(),
        raw=raw or {},
    ))


def _production_like_signal(rsi: float = 50.0, raw=None) -> SignalCandidate:
    return attach_shadow_gate_metadata(SignalCandidate(
        symbol="BTCUSDT",
        timeframe="15m",
        direction="LONG",
        entry=100.0,
        tp=107.5,
        sl=95.0,
        rr_ratio=1.5,
        rsi=rsi,
        atr_pct=0.01,
        market_phase="unclear",
        session="US",
        setup_type="unknown",
        trend_htf="Long",
        signal_source="production_like_raw_live",
        **PRODUCTION_LIKE_RAW_METADATA.as_candidate_kwargs(),
        raw=raw or {"market_mode_15m": "NO_TRADE:flat_no_impulse_no_extreme"},
    ))


def test_live_paper_storage_persists_and_restores_open_positions(tmp_path):
    storage = LivePaperStorage(tmp_path)
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio, fee_rate=0, slippage_pct=0)
    broker.open_position(_signal())

    storage.save_open_positions({"baseline_rr15": portfolio})
    restored_portfolio = PaperPortfolio("baseline_rr15")
    restored = storage.restore_open_positions({"baseline_rr15": restored_portfolio})

    assert restored == 1
    assert len(restored_portfolio.open_positions) == 1
    assert restored_portfolio.open_positions[0].symbol == "BTCUSDT"


def test_live_paper_storage_appends_closed_trades(tmp_path):
    storage = LivePaperStorage(tmp_path)
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio, fee_rate=0, slippage_pct=0)
    broker.open_position(_signal())
    first = broker.update_positions({"high": 111.0, "low": 99.0})
    storage.append_closed_trades(first)
    broker.open_position(_signal())
    second = broker.update_positions({"high": 101.0, "low": 94.0})
    storage.append_closed_trades(second)

    assert storage.closed_trades_count() == 2
    assert storage.closed_trades_path.exists()


def test_live_paper_storage_serializes_shadow_gate_enrichment(tmp_path):
    storage = LivePaperStorage(tmp_path)
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio, fee_rate=0, slippage_pct=0)
    broker.open_position(_signal(rsi=32.0))
    closed = broker.update_positions({"high": 101.0, "low": 94.0})

    storage.append_closed_trades(closed)
    text = storage.closed_trades_path.read_text(encoding="utf-8")

    assert "production_would_allow" in text
    assert "production_block_reasons" in text
    assert "shadow_gate_block_reasons" in text
    assert "rsi_below_35" in text


def test_closed_trades_include_candidate_source_metadata(tmp_path):
    storage = LivePaperStorage(tmp_path)
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio, fee_rate=0, slippage_pct=0)
    broker.open_position(_production_like_signal())
    closed = broker.update_positions({"high": 108.0, "low": 99.0})

    storage.append_closed_trades(closed)
    text = storage.closed_trades_path.read_text(encoding="utf-8")

    assert "candidate_source" in text
    assert "production_like_raw" in text
    assert "candidate_source_version" in text
    assert "v1" in text


def test_live_lifecycle_restores_open_positions_and_closes_tp(monkeypatch, tmp_path):
    calls = [
        _klines(close_time=1_700_000_000_000, high=101.0, low=99.0),
        _klines(close_time=1_700_000_100_000, high=111.0, low=99.0),
    ]
    signals = [_signal(), None]
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *args, **kwargs: calls.pop(0))
    monkeypatch.setattr("src.live_research_engine.signal_from_klines", lambda *args, **kwargs: signals.pop(0))
    store = RuntimeStatusStore(tmp_path / "runtime/runtime_status.json")

    first = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)
    first.run(["BTCUSDT"], "15m", max_iterations=1)
    assert LivePaperStorage(tmp_path).load_open_positions()

    second = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)
    second.run(["BTCUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert status["open_virtual_positions_count"] == 0
    assert status["closed_trades_count"] > 0
    assert LivePaperStorage(tmp_path).closed_trades_count() == status["closed_trades_count"]


def test_live_lifecycle_ignores_short_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *args, **kwargs: _klines())
    monkeypatch.setattr("src.live_research_engine.signal_from_klines", lambda *args, **kwargs: _signal("SHORT"))
    store = RuntimeStatusStore(tmp_path / "runtime/runtime_status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    result = engine.run(["BTCUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert result["events"] == []
    assert status["ignored_short_candidates_count"] == 1
    assert status["rejected_candidates_count"] == 1
    assert status["last_rejected_candidate_reason"] == "short_disabled_live_paper_mvp"
    assert status["open_virtual_positions_count"] == 0


def test_live_lifecycle_rejects_unsupported_candidate_source(monkeypatch, tmp_path):
    signal = _signal("LONG")
    signal.candidate_source = "unsupported_source"
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *args, **kwargs: _klines())
    monkeypatch.setattr("src.live_research_engine.signal_from_klines", lambda *args, **kwargs: signal)
    store = RuntimeStatusStore(tmp_path / "runtime/runtime_status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    result = engine.run(["BTCUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert result["events"] == []
    assert status["rejected_candidates_count"] == 1
    assert "Unsupported candidate_source" in status["last_rejected_candidate_reason"]


def test_runtime_status_is_telegram_compatible_and_safe(monkeypatch, tmp_path):
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *args, **kwargs: _klines())
    monkeypatch.setattr("src.live_research_engine.signal_from_klines", lambda *args, **kwargs: None)
    store = RuntimeStatusStore(tmp_path / "runtime/runtime_status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    engine.run(["BTCUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert status["mode"] == "live_paper_lifecycle_mvp"
    assert status["interface_target"] == "telegram"
    assert status["cli_is_fallback"] is True
    assert status["direction"] == "LONG"
    assert status["candidate_source"] == "simplified_placeholder"
    assert status["candidate_source_version"] == "v1"
    assert status["is_placeholder"] is True
    assert status["candidate_source_is_placeholder"] is True
    assert status["edge_conclusions_allowed"] is False
    assert status["candidate_source_warning"] == "technical smoke source only; do not use for edge conclusions"
    assert status["direction_support"] == "LONG_AND_SHORT"
    assert status["source_description"] == "MA/ATR simplified placeholder for technical live paper smoke testing only"
    assert status["live_direction_policy"] == "LONG_ONLY"
    assert status["shadow_gates_enabled"] is True
    assert status["raw_candidates_count"] == 0
    assert status["production_would_allow_count"] == 0
    assert status["production_would_block_count"] == 0
    assert status["shadow_blocked_but_tracked_count"] == 0
    assert "rsi_gate" in status["shadow_gate_block_counts"]
    assert status["research_pack_2_enabled"] is False
    assert status["storage_paths"]["open_positions"].endswith("open_positions.json")
    assert status["storage_paths"]["closed_trades"].endswith("closed_trades.csv")
    assert status["storage_paths"]["runtime_status"].endswith("runtime_status.json")
    assert status["safety_status"]["public_data_only"] is True
    assert status["safety_status"]["private_api_used"] is False
    assert status["safety_status"]["real_orders_enabled"] is False
    assert status["safety_status"]["testnet_orders_enabled"] is False
    assert "closed_trades_count" in status["checkpoint_progress"]
    assert "next_checkpoint" in status["checkpoint_progress"]
    assert len(HypothesisRegistry().enabled()) == 15


def test_shadow_blocked_candidate_still_reaches_hypothesis_and_paper_flow(monkeypatch, tmp_path):
    blocked_signal = _signal("LONG", rsi=32.0)
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *args, **kwargs: _klines())
    monkeypatch.setattr("src.live_research_engine.signal_from_klines", lambda *args, **kwargs: blocked_signal)
    store = RuntimeStatusStore(tmp_path / "runtime/runtime_status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    result = engine.run(["BTCUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert result["events"]
    assert len(result["portfolios"]["baseline_rr15"].open_positions) == 1
    assert status["raw_candidates_count"] == 1
    assert status["production_would_block_count"] == 1
    assert status["production_would_allow_count"] == 0
    assert status["shadow_blocked_but_tracked_count"] == 1
    assert status["shadow_gate_block_counts"]["rsi_gate"] == 1
    assert status["last_shadow_block_reasons"] == ["rsi_below_35"]


def test_production_like_raw_source_status_and_shadow_blocked_flow(monkeypatch, tmp_path):
    blocked_signal = _production_like_signal()
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *args, **kwargs: _klines())
    monkeypatch.setattr(
        "src.live_research_engine.production_like_raw_signal_from_klines",
        lambda *args, **kwargs: blocked_signal,
    )
    store = RuntimeStatusStore(tmp_path / "runtime/runtime_status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    result = engine.run(
        ["BTCUSDT"],
        "15m",
        max_iterations=1,
        candidate_source="production_like_raw",
    )
    status = store.read()

    assert result["events"]
    assert result["candidate_source"] == "production_like_raw"
    assert result["candidate_source_version"] == "v1"
    assert result["is_placeholder"] is False
    assert result["edge_conclusions_allowed"] is False
    assert result["direction_support"] == "LONG_ONLY"
    assert status["candidate_source"] == "production_like_raw"
    assert status["candidate_source_version"] == "v1"
    assert status["is_placeholder"] is False
    assert status["edge_conclusions_allowed"] is False
    assert status["direction_support"] == "LONG_ONLY"
    assert status["raw_candidates_count"] == 1
    assert status["production_would_block_count"] == 1
    assert status["shadow_blocked_but_tracked_count"] == 1
    assert status["shadow_gate_block_counts"]["market_mode_15m_gate"] == 1
    assert result["events"][0]["candidate_source"] == "production_like_raw"
