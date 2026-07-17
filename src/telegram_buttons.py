from __future__ import annotations

from dataclasses import dataclass


CALLBACK_START_CONFIRM = "control:start_live_confirm"
CALLBACK_START_LIVE = "control:start_live"
CALLBACK_STOP_LIVE = "control:stop_live"
CALLBACK_STOP_LIVE_CONFIRMED = "control:stop_live_confirmed"
CALLBACK_RESTART_LIVE = "control:restart_live"
CALLBACK_STATUS = "control:status"
CALLBACK_SETTINGS = "control:settings"
CALLBACK_DIAGNOSTICS = "control:diagnostics"
CALLBACK_CANCEL = "control:cancel"
CALLBACK_MAIN_MENU = "control:main_menu"
CALLBACK_LATEST_REPORT = "control:latest_report"
CALLBACK_SAFETY = "control:safety"
CALLBACK_SOURCE = "control:source"
CALLBACK_OPEN_TRADES = "control:open_trades"
CALLBACK_CLOSED_TRADES = "control:closed_trades"
CALLBACK_GATES = "control:gates"
CALLBACK_EXPORT_DATA = "control:export_data"

FORBIDDEN_CALLBACKS = {
    "control:real_order",
    "control:testnet_order",
    "control:enable_real_orders",
    "control:enable_testnet_orders",
}


@dataclass(frozen=True)
class TelegramResponse:
    text: str
    reply_markup: dict | None = None
    documents: tuple[str, ...] = ()


def main_control_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "▶ Start Research", "callback_data": CALLBACK_START_CONFIRM}],
            [
                {"text": "⏹ Stop Research", "callback_data": CALLBACK_STOP_LIVE},
                {"text": "📊 Status", "callback_data": CALLBACK_STATUS},
            ],
            [
                {"text": "📦 Export Data", "callback_data": CALLBACK_EXPORT_DATA},
                {"text": "⚙ Settings", "callback_data": CALLBACK_SETTINGS},
            ],
            [
                {"text": "🧪 Diagnostics", "callback_data": CALLBACK_DIAGNOSTICS},
            ],
        ]
    }


def start_live_confirmation_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "Confirm Start", "callback_data": CALLBACK_START_LIVE}],
            [{"text": "Cancel", "callback_data": CALLBACK_CANCEL}],
        ]
    }


def stop_live_confirmation_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "Confirm Stop", "callback_data": CALLBACK_STOP_LIVE_CONFIRMED}],
            [{"text": "Cancel", "callback_data": CALLBACK_CANCEL}],
        ]
    }


def diagnostics_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "Restart Research", "callback_data": CALLBACK_RESTART_LIVE}],
            [{"text": "Back", "callback_data": CALLBACK_MAIN_MENU}],
        ]
    }
