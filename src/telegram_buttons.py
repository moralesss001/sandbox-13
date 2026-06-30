from __future__ import annotations

from dataclasses import dataclass


CALLBACK_START_CONFIRM = "control:start_live_confirm"
CALLBACK_START_LIVE = "control:start_live"
CALLBACK_STOP_LIVE = "control:stop_live"
CALLBACK_RESTART_LIVE = "control:restart_live"
CALLBACK_STATUS = "control:status"
CALLBACK_LATEST_REPORT = "control:latest_report"
CALLBACK_SAFETY = "control:safety"

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


def main_control_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "Start Live Research", "callback_data": CALLBACK_START_CONFIRM}],
            [
                {"text": "Stop Live Research", "callback_data": CALLBACK_STOP_LIVE},
                {"text": "Restart Live Research", "callback_data": CALLBACK_RESTART_LIVE},
            ],
            [
                {"text": "Live Status", "callback_data": CALLBACK_STATUS},
                {"text": "Latest Report", "callback_data": CALLBACK_LATEST_REPORT},
                {"text": "Safety", "callback_data": CALLBACK_SAFETY},
            ],
        ]
    }


def start_live_confirmation_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "Confirm Start Live Research", "callback_data": CALLBACK_START_LIVE}],
            [{"text": "Safety", "callback_data": CALLBACK_SAFETY}],
        ]
    }

