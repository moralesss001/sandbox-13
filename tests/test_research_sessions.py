from __future__ import annotations

import json
from hashlib import sha256

import pandas as pd
import pytest

from src.candidate_sources import SIMPLIFIED_PLACEHOLDER_METADATA
from src.command_queue import CommandQueue
from src.hypothesis_runner import HypothesisRunner
from src.live_paper_storage import LivePaperStorage
from src.live_research_engine import LiveResearchEngine
from src.order_models import SignalCandidate, ensure_candidate_id
from src.paper_broker import PaperBroker
from src.portfolio import PaperPortfolio
from src.research_session_manager import LEGACY_SESSION_ID, ResearchSessionManager
from src.runtime_status import RuntimeStatusStore
from src.telegram_export import TelegramDataExporter


def _snapshot() -> dict:
    return {
        "timeframe": "15m",
        "direction": "LONG_ONLY",
        "candidate_source": "production_like_raw",
        "candidate_source_version": "v2",
        "configured_symbols": ["BTCUSDT"],
        "hypotheses": [{"hypothesis_id": "baseline_rr15", "version": "test"}],
        "hard_shadow_gates": {"rsi": {"minimum": 35.0}},
        "rr_tp_sl": {"rr_ratio": 1.5},
        "paper_trading": {"fee_rate": 0.0004, "slippage_pct": 0.0005},
        "safety": {"real_orders_enabled": False, "testnet_orders_enabled": False},
    }


def _klines(close_time: int, high: float = 101.0, low: float = 99.0) -> pd.DataFrame:
    rows = []
    for index in range(20):
        rows.append(
            {
                "open_time": close_time - (20 - index) * 900_000,
                "open": 100.0,
                "high": high if index == 19 else 100.5,
                "low": low if index == 19 else 99.5,
                "close": 100.0,
                "volume": 1.0,
                "close_time": close_time + index,
            }
        )
    return pd.DataFrame(rows)


def _signal(session_id: str | None = None, close_time: int = 1) -> SignalCandidate:
    return SignalCandidate(
        symbol="BTCUSDT",
        timeframe="15m",
        direction="LONG",
        entry=100.0,
        tp=107.5,
        sl=95.0,
        rr_ratio=1.5,
        session_id=session_id,
        created_at="2026-07-22T00:00:00+00:00",
        rsi=50.0,
        candidate_source=SIMPLIFIED_PLACEHOLDER_METADATA.candidate_source,
        candidate_source_version=SIMPLIFIED_PLACEHOLDER_METADATA.candidate_source_version,
        raw={"close_time": close_time},
    )


def _manager(tmp_path) -> ResearchSessionManager:
    manager = ResearchSessionManager(tmp_path)
    manager.ensure_initialized()
    return manager


def test_first_start_creates_isolated_session_contract(tmp_path):
    manager = _manager(tmp_path)
    session_id, paths = manager.create_session(_snapshot())

    assert session_id.startswith("research-")
    assert paths.root.is_dir()
    assert json.loads(paths.open_positions.read_text(encoding="utf-8")) == []
    assert paths.closed_trades.read_text(encoding="utf-8") == ""
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    snapshot = json.loads(paths.config_snapshot.read_text(encoding="utf-8"))
    status = RuntimeStatusStore(paths.runtime_status).read()
    assert manifest["session_id"] == session_id
    assert manifest["legacy"] is False
    assert snapshot["session_id"] == session_id
    assert status["raw_candidates_count"] == 0
    assert status["open_positions_count"] == 0
    assert status["closed_trades_count"] == 0
    assert manager.global_status_store.read()["active_session_id"] == session_id
    assert manager.global_status_store.read()["control_state"] == "session_preparing"
    assert json.loads(manager.legacy_index_path.read_text(encoding="utf-8"))["session_id"] == LEGACY_SESSION_ID


def test_start_is_rejected_until_previous_session_is_fully_stopped(tmp_path):
    manager = _manager(tmp_path)
    first_id, _ = manager.create_session(_snapshot())

    with pytest.raises(RuntimeError):
        manager.create_session(_snapshot())

    manager.global_status_store.update(control_state="stop_requested")
    with pytest.raises(RuntimeError):
        manager.create_session(_snapshot())

    manager.finalize_session(
        first_id,
        stop_reason="STOP_LIVE_RESEARCH",
        unresolved_open_positions_count=0,
        latest_report_path=None,
    )
    second_id, _ = manager.create_session(_snapshot())
    assert second_id != first_id


def test_stale_finalize_cannot_overwrite_new_active_session(tmp_path):
    manager = _manager(tmp_path)
    first_id, _ = manager.create_session(_snapshot())
    manager.finalize_session(
        first_id,
        stop_reason="STOP_LIVE_RESEARCH",
        unresolved_open_positions_count=0,
        latest_report_path=None,
    )
    second_id, _ = manager.create_session(_snapshot())

    manager.finalize_session(
        first_id,
        stop_reason="late_old_worker",
        unresolved_open_positions_count=0,
        latest_report_path=None,
    )

    global_status = manager.global_status_store.read()
    assert global_status["active_session_id"] == second_id
    assert global_status["control_state"] == "session_preparing"


def test_session_id_propagates_candidate_position_trade_and_legacy_hash_is_stable(tmp_path):
    manager = _manager(tmp_path)
    session_id, _ = manager.create_session(_snapshot())
    signal = _signal(session_id=session_id)
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio, fee_rate=0, slippage_pct=0)

    broker.open_position(signal)
    position = portfolio.open_positions[0]
    trade = broker.update_positions({"high": 108.0, "low": 99.0})[0]

    assert position.session_id == session_id
    assert trade.session_id == session_id

    legacy = _signal(session_id=None)
    legacy_material_id = ensure_candidate_id(legacy)
    legacy_material = "|".join(
        [
            legacy.candidate_source,
            legacy.candidate_source_version,
            legacy.symbol,
            legacy.timeframe,
            legacy.direction,
            str(legacy.raw["close_time"]),
            legacy.setup_type.lower(),
        ]
    )
    expected_legacy_id = f"candidate-{sha256(legacy_material.encode('utf-8')).hexdigest()[:24]}"
    assert legacy_material_id == expected_legacy_id


def test_checkpoint_baseline_then_first_new_candle_is_processed(monkeypatch, tmp_path):
    manager = _manager(tmp_path)
    session_id, paths = manager.create_session(_snapshot())
    queue = CommandQueue(tmp_path / "runtime/commands.jsonl")
    queue.enqueue("START_LIVE_PAPER", requested_by="test", payload={"session_id": session_id})
    close_one = 1_800_000_000_000
    frames = [_klines(close_one), _klines(close_one + 900_000)]
    signals = [_signal(close_time=close_one + 900_000)]
    monkeypatch.setattr(
        "src.live_research_engine.get_exchange_info",
        lambda **_kwargs: {
            "symbols": [{
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "contractType": "PERPETUAL",
                "quoteAsset": "USDT",
            }]
        },
    )
    monkeypatch.setattr(
        "src.live_research_engine.get_latest_klines",
        lambda *_args, **_kwargs: frames.pop(0),
    )
    monkeypatch.setattr(
        "src.live_research_engine.signal_from_klines",
        lambda *_args, **_kwargs: signals.pop(0),
    )
    monkeypatch.setattr("src.live_research_engine.time.sleep", lambda *_args: None)
    engine = LiveResearchEngine(
        {"api": {"mode": "paper"}, "safety": {}},
        data_root=paths.root,
        status_store=manager.global_status_store,
        command_queue=queue,
        session_id=session_id,
        session_manager=manager,
    )
    monkeypatch.setattr(engine, "_now_ms", lambda: close_one + 1_000_000)

    result = engine.run(
        ["BTCUSDT"],
        "15m",
        max_iterations=2,
        candidate_source="simplified_placeholder",
    )

    status = RuntimeStatusStore(paths.runtime_status).read()
    assert status["raw_candidates_count"] == 1
    assert status["last_processed_candles"]["BTCUSDT:15m"] == str(close_one + 900_019)
    assert result["events"]
    assert {event["session_id"] for event in result["events"]} == {session_id}
    positions = LivePaperStorage(paths.root).load_open_positions()
    assert positions
    assert {position.session_id for position in positions} == {session_id}


def test_stop_marks_unresolved_and_second_start_is_clean(monkeypatch, tmp_path):
    manager = _manager(tmp_path)
    first_id, first_paths = manager.create_session(_snapshot())
    storage = LivePaperStorage(first_paths.root)
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio)
    broker.open_position(_signal(session_id=first_id))
    storage.save_open_positions({"baseline_rr15": portfolio})
    manager.session_status_store(first_id).update(
        status="running",
        raw_candidates_count=7,
        open_positions_count=1,
        closed_trades_count=0,
        raw_candidates_lifetime=12,
        closed_trades_lifetime=3,
    )
    manager.global_status_store.update(
        control_state="stop_requested",
        lifetime_raw_candidates=12,
        raw_candidates_lifetime=12,
        lifetime_closed_trades=3,
        closed_trades_lifetime=3,
    )
    queue = CommandQueue(tmp_path / "runtime/commands.jsonl")
    queue.enqueue("STOP_LIVE_RESEARCH", requested_by="test", payload={"session_id": first_id})
    engine = LiveResearchEngine(
        {"api": {"mode": "paper"}, "safety": {}},
        data_root=first_paths.root,
        status_store=manager.global_status_store,
        command_queue=queue,
        session_id=first_id,
        session_manager=manager,
    )

    result = engine.run(["BTCUSDT"], "15m", max_iterations=1)

    first_manifest = json.loads(first_paths.manifest.read_text(encoding="utf-8"))
    first_positions = json.loads(first_paths.open_positions.read_text(encoding="utf-8"))
    global_status = manager.global_status_store.read()
    assert first_manifest["status"] == "stopped"
    assert first_manifest["ended_at"]
    assert first_manifest["unresolved_open_positions_count"] == 1
    assert first_positions[0]["session_final_status"] == "UNRESOLVED_AT_SESSION_END"
    assert result["paths"]["final_stop_report"]
    assert first_paths.reports.joinpath(
        result["paths"]["final_stop_report"].split("/")[-1]
    ).exists()
    assert global_status["control_state"] == "stopped"
    assert global_status["active_session_id"] is None
    assert global_status["last_session_id"] == first_id

    second_id, second_paths = manager.create_session(_snapshot())
    second_status = RuntimeStatusStore(second_paths.runtime_status).read()
    assert second_id != first_id
    assert json.loads(second_paths.open_positions.read_text(encoding="utf-8")) == []
    assert second_paths.closed_trades.read_text(encoding="utf-8") == ""
    assert second_status["raw_candidates_count"] == 0
    assert manager.global_status_store.read()["lifetime_raw_candidates"] == 12
    assert json.loads(first_paths.open_positions.read_text(encoding="utf-8")) == first_positions


def test_export_selects_active_last_and_explicit_session_without_legacy(tmp_path):
    manager = _manager(tmp_path)
    first_id, first_paths = manager.create_session(_snapshot())
    manager.finalize_session(
        first_id,
        stop_reason="STOP_LIVE_RESEARCH",
        unresolved_open_positions_count=0,
        latest_report_path=None,
    )
    second_id, _second_paths = manager.create_session(_snapshot())
    exporter = TelegramDataExporter(
        tmp_path,
        manager.global_status_store,
        session_manager=manager,
    )

    active = exporter.build()
    explicit = exporter.build(first_id)
    invalid = exporter.build("../../escape")

    assert second_id in active.message
    assert first_id in explicit.message
    assert {"manifest.json", "config_snapshot.json", "runtime_status.json"}.issubset(
        {path.split("/")[-1] for path in explicit.documents}
    )
    assert all(first_id in path for path in explicit.documents)
    assert str(tmp_path / "paper_trades/closed_trades.csv") not in explicit.documents
    assert invalid.documents == ()
    assert "not found" in invalid.message

    manager.finalize_session(
        second_id,
        stop_reason="STOP_LIVE_RESEARCH",
        unresolved_open_positions_count=0,
        latest_report_path=None,
    )
    fallback = exporter.build()
    assert second_id in fallback.message


def test_legacy_records_without_session_fields_still_load(tmp_path):
    storage = LivePaperStorage(tmp_path)
    position = _signal()
    portfolio = PaperPortfolio("baseline_rr15")
    PaperBroker(portfolio).open_position(position)
    row = dict(portfolio.open_positions[0].__dict__)
    row.pop("session_id", None)
    row.pop("session_final_status", None)
    storage.open_positions_path.write_text(json.dumps([row]), encoding="utf-8")

    loaded = storage.load_open_positions()

    assert len(loaded) == 1
    assert loaded[0].session_id is None
    assert loaded[0].session_final_status is None


def test_closed_trades_restore_session_portfolio_metrics_after_process_restart(tmp_path):
    storage = LivePaperStorage(tmp_path)
    first = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(first, fee_rate=0, slippage_pct=0)
    broker.open_position(_signal(session_id="research-20260722T000000000000Z-1234abcd"))
    closed = broker.update_positions({"high": 108.0, "low": 99.0})
    storage.append_closed_trades(closed)

    restored = PaperPortfolio("baseline_rr15")
    restored_count = storage.restore_closed_trades({"baseline_rr15": restored})

    assert restored_count == 1
    assert len(restored.closed_trades) == 1
    assert restored.net_R == first.net_R
    assert restored.balance == first.balance


def test_mark_open_positions_unresolved_preserves_without_synthetic_exit(tmp_path):
    storage = LivePaperStorage(tmp_path)
    portfolio = PaperPortfolio("baseline_rr15")
    PaperBroker(portfolio).open_position(
        _signal(session_id="research-20260722T000000000000Z-1234abcd")
    )
    storage.save_open_positions({"baseline_rr15": portfolio})

    count = storage.mark_open_positions_unresolved()
    rows = json.loads(storage.open_positions_path.read_text(encoding="utf-8"))

    assert count == 1
    assert rows[0]["session_final_status"] == "UNRESOLVED_AT_SESSION_END"
    assert storage.closed_trades_count() == 0


def test_hypothesis_metrics_restore_session_events_after_process_restart(tmp_path):
    session_id = "research-20260722T000000000000Z-1234abcd"
    first = HypothesisRunner(data_root=tmp_path, session_id=session_id)
    first.events = [
        {
            "session_id": session_id,
            "candidate_id": "candidate-1",
            "hypothesis_id": "baseline_rr15",
            "decision": "BLOCK",
            "historical_result": "loss",
        }
    ]
    first.save_artifacts()

    restored = HypothesisRunner(data_root=tmp_path, session_id=session_id)
    metrics = restored.metrics()["baseline_rr15"]

    assert metrics["trades_blocked"] == 1
    assert metrics["blocked_losses"] == 1
    assert metrics["missed_wins"] == 0
