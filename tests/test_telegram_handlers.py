from src.command_queue import CommandQueue
from src.runtime_status import RuntimeStatusStore
from src.telegram_buttons import (
    CALLBACK_CANCEL,
    CALLBACK_CLOSED_TRADES,
    CALLBACK_DIAGNOSTICS,
    CALLBACK_GATES,
    CALLBACK_OPEN_TRADES,
    CALLBACK_SAFETY,
    CALLBACK_SETTINGS,
    CALLBACK_SOURCE,
    CALLBACK_START_CONFIRM,
    CALLBACK_START_LIVE,
    CALLBACK_STOP_LIVE,
    CALLBACK_STOP_LIVE_CONFIRMED,
    FORBIDDEN_CALLBACKS,
    main_control_keyboard,
)
from src.telegram_config import TelegramConfig
from src.telegram_control import TelegramControlPanel
from src.telegram_handlers import TelegramHandlers
from src.universe import CONTRACT_UNIVERSE


def _handlers(tmp_path):
    status_store = RuntimeStatusStore(tmp_path / "status.json")
    status_store.update(
        mode="paper",
        symbols=["BTCUSDT"],
        timeframe="15m",
        direction="LONG",
        candidate_source="production_like_raw",
        candidate_source_version="v1",
        is_placeholder=False,
        edge_conclusions_allowed=False,
        direction_support="LONG_ONLY",
        source_description="Production-like raw LONG candidate source before hard-gate rejection for sandbox research",
        shadow_gates_enabled=True,
        raw_candidates_count=0,
        production_would_allow_count=0,
        production_would_block_count=0,
        shadow_blocked_but_tracked_count=0,
        safety_status={
            "api_mode": "paper",
            "telegram_read_only": True,
            "public_data_only": True,
            "private_api_used": False,
            "real_orders_enabled": False,
            "testnet_orders_enabled": False,
        },
    )
    control = TelegramControlPanel(
        status_store=status_store,
        command_queue=CommandQueue(tmp_path / "commands.jsonl"),
        data_root=tmp_path,
    )
    config = TelegramConfig(token="token", allowed_user_id="123")
    return TelegramHandlers(config, control)


def _create_session(handlers):
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


def test_unauthorized_user_is_rejected(tmp_path):
    handlers = _handlers(tmp_path)

    assert handlers.handle("/status", user_id="999") == "Unauthorized user."


def test_read_only_status_command_works(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle("/status", user_id="123")

    assert "⚪ Research Stopped" in response
    assert "raw candidates (current run): 0" in response
    assert "closed trades (lifetime): 0" in response
    assert "universe: 46 configured / 0 active / 0 unavailable" in response
    assert "execution: PAPER ONLY" in response
    assert "runtime_data_directory" not in response
    assert "last_shadow_block_reasons" not in response


def test_short_status_shows_running_state_and_duration(tmp_path):
    handlers = _handlers(tmp_path)
    session_id, paths = _create_session(handlers)
    handlers.control.session_manager.session_status_store(session_id).update(status="running")
    handlers.control.status_store.update(control_state="running")

    response = handlers.handle_callback("control:status", user_id="123")

    assert "🟢 Research Running" in response.text
    assert "runtime: " in response.text
    assert f"active session ID: {session_id}" in response.text
    assert "session status: running" in response.text


def test_telegram_buttons_exist():
    keyboard = main_control_keyboard()
    labels = [button["text"] for row in keyboard["inline_keyboard"] for button in row]

    assert labels == [
        "▶ Start Research",
        "⏹ Stop Research",
        "📊 Status",
        "📦 Export Data",
        "⚙ Settings",
        "🧪 Diagnostics",
    ]
    assert all(len(row) <= 2 for row in keyboard["inline_keyboard"])


def test_start_live_confirmation_screen(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle_message("/start_live", user_id="123")

    assert "Start Live Paper Research?" in response.text
    assert "production_like_raw v2" in response.text
    assert "PAPER ONLY" in response.text
    assert "Real orders:\nOFF" in response.text
    assert response.reply_markup is not None
    buttons = [button["text"] for row in response.reply_markup["inline_keyboard"] for button in row]
    assert buttons == ["Confirm Start", "Cancel"]


def test_start_button_shows_confirmation(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle_callback(CALLBACK_START_CONFIRM, user_id="123")

    assert "Start Live Paper Research?" in response.text


def test_unauthorized_user_cannot_press_buttons(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle_callback(CALLBACK_SAFETY, user_id="999")

    assert response.text == "Unauthorized user."


def test_forbidden_commands_are_rejected(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle("/real_order BTCUSDT", user_id="123")

    assert "forbidden" in response.lower()


def test_forbidden_trading_buttons_do_not_exist():
    keyboard = main_control_keyboard()
    callback_data = {button["callback_data"] for row in keyboard["inline_keyboard"] for button in row}

    assert callback_data.isdisjoint(FORBIDDEN_CALLBACKS)


def test_run_hypotheses_queues_only_safe_command(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle("/run_hypotheses", user_id="123")

    assert "RUN_HYPOTHESIS_REPLAY" in response


def test_stop_live_research_requests_final_stop_report(tmp_path):
    handlers = _handlers(tmp_path)
    handlers.control.status_store.update(control_state="running")

    confirmation = handlers.handle_callback(CALLBACK_STOP_LIVE, user_id="123")

    assert "Stop Live Paper Research?" in confirmation.text
    assert not (tmp_path / "commands.jsonl").exists()
    assert handlers.control.status_store.read()["control_state"] == "running"

    response = handlers.handle_callback(CALLBACK_STOP_LIVE_CONFIRMED, user_id="123")

    assert "Research stop requested." in response.text
    assert "Telegram control panel remains online." in response.text
    reports = list((tmp_path / "demo_reports").glob("stop_report_*.md"))
    assert reports
    assert "Stop Report" in reports[0].read_text(encoding="utf-8")


def test_live_start_queues_production_like_raw_safely(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle_callback(CALLBACK_START_LIVE, user_id="123")

    assert "START_LIVE_PAPER" in response.text
    assert "production_like_raw" in response.text
    status = handlers.control.status_store.read()
    assert status["control_state"] == "start_requested"
    assert status["candidate_source"] == "production_like_raw"
    assert status["edge_conclusions_allowed"] is False
    commands = CommandQueue(tmp_path / "commands.jsonl").read_all()
    assert commands[-1].command == "START_LIVE_PAPER"
    assert commands[-1].payload["timeframe"] == "15m"
    assert commands[-1].payload["symbols"] == list(CONTRACT_UNIVERSE)


def test_live_start_does_not_duplicate_running_live_paper(tmp_path):
    handlers = _handlers(tmp_path)
    handlers.control.status_store.update(control_state="running")

    response = handlers.handle_callback(CALLBACK_START_LIVE, user_id="123")

    assert response.text == "Research is already running."
    assert not (tmp_path / "commands.jsonl").exists()


def test_live_stop_when_not_running_is_clear_and_safe(tmp_path):
    handlers = _handlers(tmp_path)

    confirmation = handlers.handle_message("/live_stop", user_id="123")
    response = handlers.handle_callback(CALLBACK_STOP_LIVE_CONFIRMED, user_id="123")

    assert "Stop Live Paper Research?" in confirmation.text
    assert response.text == "Research is not running."
    assert not (tmp_path / "commands.jsonl").exists()


def test_live_status_includes_edge_warning_and_safety(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle("/live_status", user_id="123")

    assert "Live Research Diagnostics" in response
    assert "control state: stopped" in response
    assert "execution: PAPER ONLY" in response
    assert "runtime status:" in response


def test_settings_is_read_only_and_has_no_mutation_buttons(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle_callback(CALLBACK_SETTINGS, user_id="123")
    labels = [button["text"] for row in response.reply_markup["inline_keyboard"] for button in row]

    assert "Research Settings (read-only)" in response.text
    assert "source: production_like_raw" in response.text
    assert "configured symbols: 46" in response.text
    assert "RR: N/A" in response.text
    assert "execution: PAPER ONLY" in response.text
    assert "real orders: OFF" in response.text
    assert not any("change" in label.lower() or "enable" in label.lower() for label in labels)


def test_diagnostics_limits_shadow_reasons_to_last_item(tmp_path):
    handlers = _handlers(tmp_path)
    handlers.control.status_store.update(
        active_symbols=["BTCUSDT"],
        unavailable_symbols=["AGIXUSDT"],
        last_shadow_block_reasons=["rsi_below_35", "market_mode_15m_no_trade"],
        errors=[{"error": "TimeoutError: request timed out\ntraceback hidden"}],
    )

    response = handlers.handle_callback(CALLBACK_DIAGNOSTICS, user_id="123")

    assert "Live Research Diagnostics" in response.text
    assert "last error class: TimeoutError" in response.text
    assert "last shadow reason: market_mode_15m_no_trade" in response.text
    assert "last shadow reason count: 2" in response.text
    assert "active runtime universe count: 1" in response.text
    assert "unavailable symbols: AGIXUSDT" in response.text
    assert "rsi_below_35" not in response.text
    assert "traceback hidden" not in response.text


def test_cancel_returns_to_operator_panel_without_queueing(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle_callback(CALLBACK_CANCEL, user_id="123")

    assert response.text == "Operator panel."
    assert response.reply_markup == main_control_keyboard()
    assert not (tmp_path / "commands.jsonl").exists()


def test_source_command_shows_production_like_raw_metadata(tmp_path):
    handlers = _handlers(tmp_path)
    response = handlers.handle_callback(CALLBACK_SOURCE, user_id="123")

    assert "Candidate source" in response.text
    assert "candidate_source: production_like_raw" in response.text
    assert "score_analytics_only: true" in response.text
    assert "score_used_as_gate: false" in response.text
    assert "shadow_gates_enabled: True" in response.text


def test_open_trades_handles_empty_positions(tmp_path):
    handlers = _handlers(tmp_path)
    response = handlers.handle_callback(CALLBACK_OPEN_TRADES, user_id="123")

    assert response.text == "No open virtual positions."


def test_open_trades_shows_position_metadata(tmp_path):
    handlers = _handlers(tmp_path)
    _session_id, paths = _create_session(handlers)
    path = paths.open_positions
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '[{"symbol":"BTCUSDT","direction":"LONG","entry_price":100,"tp":105,"sl":95,'
        '"entry_time":"2026-07-07T00:00:00Z","candidate_source":"production_like_raw",'
        '"production_would_allow":false,"production_block_reasons":["market_mode_15m_no_trade"],'
        '"shadow_gate_block_reasons":["market_mode_15m_no_trade"]}]',
        encoding="utf-8",
    )

    response = handlers.handle("/open_trades", user_id="123")

    assert "Open virtual positions" in response
    assert "candidate_source: production_like_raw" in response
    assert "production_would_allow: False" in response
    assert "market_mode_15m_no_trade" in response


def test_closed_trades_handles_empty_file(tmp_path):
    handlers = _handlers(tmp_path)
    response = handlers.handle_callback(CALLBACK_CLOSED_TRADES, user_id="123")

    assert response.text == "No closed paper trades yet."


def test_closed_trades_shows_latest_closed_trade(tmp_path):
    handlers = _handlers(tmp_path)
    _session_id, paths = _create_session(handlers)
    path = paths.closed_trades
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "symbol,direction,entry_price,exit_price,result,r,reason,candidate_source,production_would_allow,production_block_reasons\n"
        "BTCUSDT,LONG,100,95,loss,-1,SL,production_like_raw,False,market_mode_15m_no_trade\n",
        encoding="utf-8",
    )

    response = handlers.handle("/closed_trades", user_id="123")

    assert "Latest closed paper trades" in response
    assert "result: loss / R=-1" in response
    assert "candidate_source: production_like_raw" in response


def test_gates_shows_zero_counters_when_no_closed_trades(tmp_path):
    handlers = _handlers(tmp_path)
    response = handlers.handle_callback(CALLBACK_GATES, user_id="123")

    assert "Not enough closed trades yet" in response.text
    assert "gate_saved_from_loss: 0" in response.text
    assert "production_would_block_count: 0" in response.text


def test_gates_shows_saved_missed_allowed_analytics(tmp_path):
    handlers = _handlers(tmp_path)
    session_id, paths = _create_session(handlers)
    handlers.control.session_manager.session_status_store(session_id).update(
        production_would_allow_count=2,
        production_would_block_count=2,
        shadow_blocked_but_tracked_count=2,
        shadow_gate_block_counts={"rsi_gate": 1, "market_mode_15m_gate": 1},
        last_shadow_block_reasons=["rsi_below_35"],
    )
    path = paths.closed_trades
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "production_would_allow,r\n"
        "False,-1\n"
        "False,1.5\n"
        "True,-1\n"
        "True,1.5\n",
        encoding="utf-8",
    )

    response = handlers.handle("/gates", user_id="123")

    assert "gate_saved_from_loss: 1" in response
    assert "gate_missed_profit: 1" in response
    assert "gate_allowed_loss: 1" in response
    assert "gate_allowed_profit: 1" in response
    assert "rsi_below_35" in response
