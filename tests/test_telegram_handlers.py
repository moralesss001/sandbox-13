from src.command_queue import CommandQueue
from src.runtime_status import RuntimeStatusStore
from src.telegram_buttons import (
    CALLBACK_CLOSED_TRADES,
    CALLBACK_GATES,
    CALLBACK_OPEN_TRADES,
    CALLBACK_SAFETY,
    CALLBACK_SOURCE,
    CALLBACK_START_CONFIRM,
    CALLBACK_START_LIVE,
    CALLBACK_STOP_LIVE,
    FORBIDDEN_CALLBACKS,
    main_control_keyboard,
)
from src.telegram_config import TelegramConfig
from src.telegram_control import TelegramControlPanel
from src.telegram_handlers import TelegramHandlers


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


def test_unauthorized_user_is_rejected(tmp_path):
    handlers = _handlers(tmp_path)

    assert handlers.handle("/status", user_id="999") == "Unauthorized user."


def test_read_only_status_command_works(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle("/status", user_id="123")

    assert "Crypto13Research status" in response
    assert "BTCUSDT" in response


def test_telegram_buttons_exist():
    keyboard = main_control_keyboard()
    labels = [button["text"] for row in keyboard["inline_keyboard"] for button in row]

    assert "Start Live Research" in labels
    assert "Stop Live Research" in labels
    assert "Restart Live Research" in labels
    assert "Live Status" in labels
    assert "Latest Report" in labels
    assert "Safety" in labels
    assert "Source" in labels
    assert "Open Trades" in labels
    assert "Closed Trades" in labels
    assert "Gates" in labels


def test_start_live_confirmation_screen(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle_message("/start_live", user_id="123")

    assert "Confirm Start Live Paper" in response.text
    assert response.reply_markup is not None
    buttons = [button["text"] for row in response.reply_markup["inline_keyboard"] for button in row]
    assert "Confirm Start Live Research" in buttons


def test_start_button_shows_confirmation(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle_callback(CALLBACK_START_CONFIRM, user_id="123")

    assert "Confirm Start Live Paper" in response.text


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

    response = handlers.handle_callback(CALLBACK_STOP_LIVE, user_id="123")

    assert "STOP_LIVE_RESEARCH" in response.text
    assert "Final stop report:" in response.text
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


def test_live_start_does_not_duplicate_running_live_paper(tmp_path):
    handlers = _handlers(tmp_path)
    handlers.control.status_store.update(control_state="running")

    response = handlers.handle_callback(CALLBACK_START_LIVE, user_id="123")

    assert "already running" in response.text
    assert not (tmp_path / "commands.jsonl").exists()


def test_live_stop_when_not_running_is_clear_and_safe(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle("/live_stop", user_id="123")

    assert "not running" in response.lower()
    assert not (tmp_path / "commands.jsonl").exists()


def test_live_status_includes_edge_warning_and_safety(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle("/live_status", user_id="123")

    assert "Live paper status" in response
    assert "candidate_source: production_like_raw" in response
    assert "edge_conclusions_allowed: False" in response
    assert "Do not use this as production proof yet" in response
    assert "public_data_only: True" in response
    assert "private_api_used: False" in response
    assert "real_orders_enabled: False" in response
    assert "testnet_orders_enabled: False" in response


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
    path = tmp_path / "paper_trades/open_positions.json"
    path.parent.mkdir(parents=True)
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
    path = tmp_path / "paper_trades/closed_trades.csv"
    path.parent.mkdir(parents=True)
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
    handlers.control.status_store.update(
        production_would_allow_count=2,
        production_would_block_count=2,
        shadow_blocked_but_tracked_count=2,
        shadow_gate_block_counts={"rsi_gate": 1, "market_mode_15m_gate": 1},
        last_shadow_block_reasons=["rsi_below_35"],
    )
    path = tmp_path / "paper_trades/closed_trades.csv"
    path.parent.mkdir(parents=True)
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
