from __future__ import annotations

import json
from pathlib import Path

from src.command_queue import CommandQueue
from src.live_paper_storage import LivePaperStorage
from src.live_research_engine import LiveResearchEngine
from src.order_models import SignalCandidate
from src.paper_broker import PaperBroker
from src.portfolio import PaperPortfolio
from src.runtime_status import RuntimeStatusStore
from src.telegram_config import TelegramConfig
from src.telegram_control import TelegramControlPanel
from src.telegram_handlers import TelegramHandlers
from src.universe import CONTRACT_UNIVERSE


def _signal(close_time: int = 1_700_000_000_000) -> SignalCandidate:
    return SignalCandidate(
        symbol="BTCUSDT",
        timeframe="15m",
        direction="LONG",
        entry=100.0,
        tp=105.0,
        sl=95.0,
        rr_ratio=1.0,
        created_at="2026-07-16T00:00:00+00:00",
        setup_type="rebound",
        candidate_source="production_like_raw",
        candidate_source_version="v1",
        raw={"close_time": close_time},
    )


def _handlers(tmp_path: Path, allowed_chat_id: str = "123") -> TelegramHandlers:
    storage = LivePaperStorage(tmp_path)
    store = RuntimeStatusStore(storage.runtime_status_path)
    store.update(
        mode="sandbox_run_all",
        runtime_layout="single_service",
        control_state="running",
        candidate_source="production_like_raw",
        candidate_source_version="v1",
        timeframe="15m",
        direction="LONG_ONLY",
        raw_candidates_count=68,
        raw_candidates_lifetime=68,
        raw_candidates_current_run=4,
        open_positions_count=2,
        open_positions_current=2,
        closed_trades_count=10,
        closed_trades_lifetime=10,
        errors=[],
        **storage.diagnostics(),
    )
    control = TelegramControlPanel(
        status_store=store,
        command_queue=CommandQueue(tmp_path / "runtime/commands.jsonl"),
        data_root=tmp_path,
    )
    return TelegramHandlers(
        TelegramConfig(token="token", allowed_user_id="123", allowed_chat_id=allowed_chat_id),
        control,
    )


def _create_session(handlers: TelegramHandlers):
    handlers.control.status_store.update(control_state="stopped", active_session_id=None)
    session_id, paths = handlers.control.session_manager.create_session(
        {
            "timeframe": "15m",
            "direction": "LONG_ONLY",
            "candidate_source": "production_like_raw",
            "candidate_source_version": "v2",
            "configured_symbols": list(CONTRACT_UNIVERSE),
        }
    )
    return session_id, paths


def test_storage_paths_are_absolute_consistent_and_parents_exist(tmp_path):
    storage = LivePaperStorage(tmp_path / "paper_data")
    diagnostics = storage.diagnostics()

    assert storage.data_root.is_absolute()
    assert Path(diagnostics["runtime_status_path"]).parent.exists()
    assert Path(diagnostics["open_positions_path"]).parent.exists()
    assert Path(diagnostics["closed_trades_path"]).parent.exists()


def test_duplicate_open_position_for_same_signal_is_rejected():
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio)

    first = broker.open_position(_signal())
    second = broker.open_position(_signal())

    assert first.status == "OPENED"
    assert second.status == "DUPLICATE"
    assert second.reason == "signal_already_open"
    assert len(portfolio.open_positions) == 1


def test_duplicate_closed_trade_is_not_appended(tmp_path):
    storage = LivePaperStorage(tmp_path)
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio)
    broker.open_position(_signal())
    closed = broker.update_positions({"high": 106.0, "low": 99.0})

    storage.append_closed_trades(closed)
    storage.append_closed_trades(closed)

    assert storage.closed_trades_count() == 1


def test_restore_deduplicates_positions_and_does_not_duplicate_existing_portfolio(tmp_path):
    storage = LivePaperStorage(tmp_path)
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio)
    broker.open_position(_signal())
    row = dict(portfolio.open_positions[0].__dict__)
    storage.open_positions_path.write_text(json.dumps([row, row]), encoding="utf-8")
    restored = PaperPortfolio("baseline_rr15")

    first = storage.restore_open_positions({"baseline_rr15": restored})
    second = storage.restore_open_positions({"baseline_rr15": restored})

    assert first == 1
    assert second == 0
    assert len(restored.open_positions) == 1


def test_closed_signal_cannot_reopen_after_restart(tmp_path):
    storage = LivePaperStorage(tmp_path)
    first_portfolio = PaperPortfolio("baseline_rr15")
    first_broker = PaperBroker(first_portfolio)
    first_broker.open_position(_signal())
    closed = first_broker.update_positions({"high": 106.0, "low": 99.0})
    storage.append_closed_trades(closed)

    restored_portfolio = PaperPortfolio("baseline_rr15")
    restored_broker = PaperBroker(
        restored_portfolio,
        known_closed_signal_ids=storage.closed_signal_ids(),
    )
    result = restored_broker.open_position(_signal())

    assert result.status == "DUPLICATE"
    assert result.reason == "signal_already_closed"
    assert not restored_portfolio.open_positions


def test_restart_does_not_restore_position_already_present_in_closed_trades(tmp_path):
    storage = LivePaperStorage(tmp_path)
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio)
    broker.open_position(_signal())
    storage.save_open_positions({"baseline_rr15": portfolio})
    closed = broker.update_positions({"high": 106.0, "low": 99.0})
    storage.append_closed_trades(closed)
    restored = PaperPortfolio("baseline_rr15")

    count = storage.restore_open_positions(
        {"baseline_rr15": restored},
        closed_signal_ids=storage.closed_signal_ids(),
    )

    assert count == 0
    assert not restored.open_positions


def test_live_stop_preserves_single_service_metadata(tmp_path):
    handlers = _handlers(tmp_path)

    confirmation = handlers.handle_message("/live_stop", user_id="123", chat_id="123")
    assert "Stop Live Paper Research?" in confirmation.text
    assert handlers.control.status_store.read()["control_state"] == "running"

    response = handlers.handle_callback("control:stop_live_confirmed", user_id="123", chat_id="123")
    status = handlers.control.status_store.read()

    assert "Research stop requested." in response.text
    assert "Telegram control panel remains online." in response.text
    assert status["mode"] == "sandbox_run_all"
    assert status["runtime_layout"] == "single_service"
    assert status["control_state"] == "stop_requested"


def test_live_start_preserves_single_service_and_does_not_queue_second_start(tmp_path):
    handlers = _handlers(tmp_path)
    handlers.control.status_store.update(control_state="stopped")

    first = handlers.handle_callback("control:start_live", user_id="123", chat_id="123")
    second = handlers.handle_callback("control:start_live", user_id="123", chat_id="123")
    status = handlers.control.status_store.read()
    commands = handlers.control.command_queue.read_all()

    assert "START_LIVE_PAPER" in first.text
    assert "already running" in second.text
    assert len([item for item in commands if item.command == "START_LIVE_PAPER"]) == 1
    assert status["mode"] == "sandbox_run_all"
    assert status["runtime_layout"] == "single_service"


def test_export_data_rejects_unauthorized_user_and_chat(tmp_path):
    handlers = _handlers(tmp_path, allowed_chat_id="123")

    wrong_user = handlers.handle_message("/export_data", user_id="999", chat_id="123")
    wrong_chat = handlers.handle_message("/export_data", user_id="123", chat_id="999")

    assert wrong_user.text == "Unauthorized user."
    assert wrong_chat.text == "Unauthorized user."
    assert not wrong_user.documents
    assert not wrong_chat.documents


def test_export_data_sends_only_allowlisted_files_and_sanitizes_status(tmp_path):
    handlers = _handlers(tmp_path)
    session_id, paths = _create_session(handlers)
    storage = LivePaperStorage(paths.root)
    storage.open_positions_path.write_text(
        '[{"signal_id":"abc","api_key":"OPEN_SECRET",'
        '"reason":"https://api.telegram.org/bot12345:OPEN_TOKEN/getUpdates"}]',
        encoding="utf-8",
    )
    storage.closed_trades_path.write_text(
        "signal_id,result,secret_note,reason\n"
        "abc,win,CLOSED_SECRET,https://api.telegram.org/bot12345:CLOSED_TOKEN/getUpdates\n",
        encoding="utf-8",
    )
    handlers.control.session_manager.session_status_store(session_id).update(
        errors=[{"error": "request failed at https://api.telegram.org/bot12345:TOP_SECRET/getUpdates"}],
        telegram_token="must_not_export",
        candidate_source="bot12345:SUMMARY_SECRET",
    )
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=secret", encoding="utf-8")

    response = handlers.handle_message("/export_data", user_id="123", chat_id="123")
    names = {Path(path).name for path in response.documents}
    safe_status_path = next(Path(path) for path in response.documents if Path(path).name == "runtime_status.json")
    safe_open_path = next(Path(path) for path in response.documents if Path(path).name == "open_positions.json")
    safe_closed_path = next(Path(path) for path in response.documents if Path(path).name == "closed_trades.csv")
    safe_summary_path = next(Path(path) for path in response.documents if Path(path).name == "run_summary.json")
    exported = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (safe_status_path, safe_open_path, safe_closed_path, safe_summary_path)
    )

    assert names == {
        "manifest.json",
        "config_snapshot.json",
        "runtime_status.json",
        "open_positions.json",
        "closed_trades.csv",
        "run_summary.json",
    }
    assert ".env" not in names
    assert "TOP_SECRET" not in exported
    assert "must_not_export" not in exported
    assert "OPEN_SECRET" not in exported
    assert "OPEN_TOKEN" not in exported
    assert "CLOSED_SECRET" not in exported
    assert "CLOSED_TOKEN" not in exported
    assert "SUMMARY_SECRET" not in exported
    assert "[REDACTED]" in exported


def test_export_data_reports_missing_files_without_crash(tmp_path):
    handlers = _handlers(tmp_path)
    _session_id, paths = _create_session(handlers)
    paths.open_positions.unlink()
    paths.closed_trades.unlink()

    response = handlers.handle_message("/export_data", user_id="123", chat_id="123")

    assert "Unavailable:" in response.text
    assert "- open_positions.json" in response.text
    assert "- closed_trades.csv" in response.text
    assert str(tmp_path.resolve()) not in response.text
    assert {Path(path).name for path in response.documents} == {
        "manifest.json",
        "config_snapshot.json",
        "runtime_status.json",
        "run_summary.json",
    }


def test_run_summary_contains_clarified_counter_semantics(tmp_path):
    handlers = _handlers(tmp_path)
    session_id, _paths = _create_session(handlers)
    handlers.control.session_manager.session_status_store(session_id).update(
        configured_symbols=list(CONTRACT_UNIVERSE),
        raw_candidates_count=4,
        open_positions_count=2,
        closed_trades_count=10,
    )
    handlers.control.status_store.update(
        lifetime_raw_candidates=68,
        lifetime_closed_trades=10,
    )
    response = handlers.handle_message("/export_data", user_id="123", chat_id="123")
    summary_path = next(Path(path) for path in response.documents if Path(path).name == "run_summary.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["raw_candidates_count"] == 4
    assert summary["lifetime_raw_candidates"] == 68
    assert summary["open_positions_count"] == 2
    assert summary["lifetime_closed_trades"] == 10
    assert summary["configured_symbols_count"] == 46
    assert summary["configured_symbols"][0:2] == ["BTCUSDT", "ETHUSDT"]
    assert summary["active_symbols"] == []
    assert summary["unavailable_symbols"] == []
    assert Path(summary["session_storage_paths"]["session_root"]).parent.parent == tmp_path.resolve()


def test_engine_stop_keeps_cumulative_closed_count_and_single_service_metadata(tmp_path):
    storage = LivePaperStorage(tmp_path)
    storage.closed_trades_path.write_text(
        "signal_id,trade_id,result\nsignal-a,trade-a,win\nsignal-b,trade-b,loss\n",
        encoding="utf-8",
    )
    store = RuntimeStatusStore(storage.runtime_status_path)
    store.update(
        mode="sandbox_run_all",
        runtime_layout="single_service",
        control_state="running",
        raw_candidates_count=68,
    )
    queue = CommandQueue(tmp_path / "runtime/commands.jsonl")
    queue.enqueue("STOP_LIVE_RESEARCH", requested_by="123")
    engine = LiveResearchEngine(
        {"api": {"mode": "paper"}, "safety": {}},
        data_root=tmp_path,
        status_store=store,
        command_queue=queue,
    )

    engine.run(["BTCUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert status["closed_trades_count"] == 2
    assert status["closed_trades_lifetime"] == 2
    assert status["mode"] == "sandbox_run_all"
    assert status["runtime_layout"] == "single_service"
    assert status["control_state"] == "stopped"
