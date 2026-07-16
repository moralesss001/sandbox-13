from __future__ import annotations

from .telegram_config import TelegramConfig
from .telegram_control import TelegramControlPanel
from .telegram_buttons import (
    CALLBACK_LATEST_REPORT,
    CALLBACK_CLOSED_TRADES,
    CALLBACK_EXPORT_DATA,
    CALLBACK_GATES,
    CALLBACK_OPEN_TRADES,
    CALLBACK_RESTART_LIVE,
    CALLBACK_SAFETY,
    CALLBACK_SOURCE,
    CALLBACK_START_CONFIRM,
    CALLBACK_START_LIVE,
    CALLBACK_STATUS,
    CALLBACK_STOP_LIVE,
    FORBIDDEN_CALLBACKS,
    TelegramResponse,
)


FORBIDDEN_COMMANDS = {
    "/enable_hypothesis",
    "/disable_hypothesis",
    "/edit_hypothesis",
    "/testnet_order",
    "/real_order",
}


class TelegramHandlers:
    def __init__(self, config: TelegramConfig, control: TelegramControlPanel | None = None):
        self.config = config
        self.control = control or TelegramControlPanel()

    def handle(self, text: str, user_id: str | int | None, chat_id: str | int | None = None) -> str:
        return self.handle_message(text, user_id, chat_id).text

    def handle_message(
        self,
        text: str,
        user_id: str | int | None,
        chat_id: str | int | None = None,
    ) -> TelegramResponse:
        if not self._is_authorized(user_id, chat_id):
            return TelegramResponse("Unauthorized user.")
        text = (text or "").strip()
        command = text.split()[0] if text else "/help"
        if command in FORBIDDEN_COMMANDS:
            return TelegramResponse("Command is forbidden in read-only Telegram control panel.")
        if command == "/start":
            return TelegramResponse(
                "Crypto13Research Telegram control panel is read-only.\n" + self.control.help(),
                self.control.main_keyboard(),
            )
        if command in {"/start_live", "/live_start"}:
            text, keyboard = self.control.start_live_confirmation()
            return TelegramResponse(text, keyboard)
        if command == "/live_stop":
            return TelegramResponse(self.control.live_stop(requested_by=str(user_id)), self.control.main_keyboard())
        if command == "/live_status":
            return TelegramResponse(self.control.live_status(), self.control.main_keyboard())
        if command == "/source":
            return TelegramResponse(self.control.source(), self.control.main_keyboard())
        if command == "/open_trades":
            return TelegramResponse(self.control.open_trades(), self.control.main_keyboard())
        if command == "/closed_trades":
            return TelegramResponse(self.control.closed_trades(), self.control.main_keyboard())
        if command == "/gates":
            return TelegramResponse(self.control.gates(), self.control.main_keyboard())
        if command == "/status":
            return TelegramResponse(self.control.status(), self.control.main_keyboard())
        if command == "/safety":
            return TelegramResponse(self.control.safety(), self.control.main_keyboard())
        if command == "/hypotheses":
            return TelegramResponse(self.control.hypotheses(), self.control.main_keyboard())
        if command == "/hypothesis":
            parts = text.split(maxsplit=1)
            if len(parts) != 2:
                return TelegramResponse("Usage: /hypothesis <id>")
            try:
                return TelegramResponse(self.control.hypothesis(parts[1].strip()), self.control.main_keyboard())
            except KeyError:
                return TelegramResponse(f"Hypothesis not found: {parts[1].strip()}")
        if command == "/run_hypotheses":
            return TelegramResponse(self.control.run_hypotheses(requested_by=str(user_id)), self.control.main_keyboard())
        if command == "/latest_report":
            return TelegramResponse(self.control.latest_report(), self.control.main_keyboard())
        if command == "/suggestions":
            return TelegramResponse(self.control.suggestions(), self.control.main_keyboard())
        if command == "/portfolio":
            return TelegramResponse(self.control.portfolio(), self.control.main_keyboard())
        if command == "/events":
            return TelegramResponse(self.control.events(), self.control.main_keyboard())
        if command == "/export_data":
            result = self.control.export_data()
            return TelegramResponse(result.message, self.control.main_keyboard(), result.documents)
        if command == "/help":
            return TelegramResponse(self.control.help(), self.control.main_keyboard())
        return TelegramResponse("Unknown command.\n" + self.control.help(), self.control.main_keyboard())

    def handle_callback(
        self,
        callback_data: str,
        user_id: str | int | None,
        chat_id: str | int | None = None,
    ) -> TelegramResponse:
        if not self._is_authorized(user_id, chat_id):
            return TelegramResponse("Unauthorized user.")
        if callback_data in FORBIDDEN_CALLBACKS:
            return TelegramResponse("Callback is forbidden in read-only Telegram control panel.")
        if callback_data == CALLBACK_START_CONFIRM:
            text, keyboard = self.control.start_live_confirmation()
            return TelegramResponse(text, keyboard)
        if callback_data == CALLBACK_START_LIVE:
            return TelegramResponse(self.control.live_start(str(user_id)), self.control.main_keyboard())
        if callback_data == CALLBACK_STOP_LIVE:
            return TelegramResponse(self.control.live_stop(str(user_id)), self.control.main_keyboard())
        if callback_data == CALLBACK_RESTART_LIVE:
            return TelegramResponse(self.control.restart_live_research(str(user_id)), self.control.main_keyboard())
        if callback_data == CALLBACK_STATUS:
            return TelegramResponse(self.control.live_status(), self.control.main_keyboard())
        if callback_data == CALLBACK_LATEST_REPORT:
            return TelegramResponse(self.control.latest_report(), self.control.main_keyboard())
        if callback_data == CALLBACK_SAFETY:
            return TelegramResponse(self.control.safety(), self.control.main_keyboard())
        if callback_data == CALLBACK_SOURCE:
            return TelegramResponse(self.control.source(), self.control.main_keyboard())
        if callback_data == CALLBACK_OPEN_TRADES:
            return TelegramResponse(self.control.open_trades(), self.control.main_keyboard())
        if callback_data == CALLBACK_CLOSED_TRADES:
            return TelegramResponse(self.control.closed_trades(), self.control.main_keyboard())
        if callback_data == CALLBACK_GATES:
            return TelegramResponse(self.control.gates(), self.control.main_keyboard())
        if callback_data == CALLBACK_EXPORT_DATA:
            result = self.control.export_data()
            return TelegramResponse(result.message, self.control.main_keyboard(), result.documents)
        return TelegramResponse("Unknown control button.", self.control.main_keyboard())

    def _is_authorized(self, user_id: str | int | None, chat_id: str | int | None) -> bool:
        if not self.config.is_allowed_user(user_id):
            return False
        return chat_id is None or self.config.is_allowed_chat(chat_id)
