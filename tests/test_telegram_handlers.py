from src.command_queue import CommandQueue
from src.runtime_status import RuntimeStatusStore
from src.telegram_buttons import (
    CALLBACK_SAFETY,
    CALLBACK_START_CONFIRM,
    CALLBACK_STOP_LIVE,
    FORBIDDEN_CALLBACKS,
    main_control_keyboard,
)
from src.telegram_config import TelegramConfig
from src.telegram_control import TelegramControlPanel
from src.telegram_handlers import TelegramHandlers


def _handlers(tmp_path):
    status_store = RuntimeStatusStore(tmp_path / "status.json")
    status_store.update(mode="paper", symbols=["BTCUSDT"], timeframe="15m")
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


def test_start_live_confirmation_screen(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle_message("/start_live", user_id="123")

    assert "Confirm Start Live Research" in response.text
    assert response.reply_markup is not None
    buttons = [button["text"] for row in response.reply_markup["inline_keyboard"] for button in row]
    assert "Confirm Start Live Research" in buttons


def test_start_button_shows_confirmation(tmp_path):
    handlers = _handlers(tmp_path)

    response = handlers.handle_callback(CALLBACK_START_CONFIRM, user_id="123")

    assert "Confirm Start Live Research" in response.text


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

    response = handlers.handle_callback(CALLBACK_STOP_LIVE, user_id="123")

    assert "STOP_LIVE_RESEARCH" in response.text
    assert "Final stop report:" in response.text
    reports = list((tmp_path / "demo_reports").glob("stop_report_*.md"))
    assert reports
    assert "Stop Report" in reports[0].read_text(encoding="utf-8")
