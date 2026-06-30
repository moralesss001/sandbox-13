from __future__ import annotations

import time
from typing import Any

import requests

from .telegram_config import load_telegram_config_from_env
from .telegram_handlers import TelegramHandlers


class TelegramBot:
    def __init__(self, token: str, handlers: TelegramHandlers, poll_interval_sec: int = 3):
        self.token = token
        self.handlers = handlers
        self.poll_interval_sec = max(1, int(poll_interval_sec))
        self.base_url = f"https://api.telegram.org/bot{token}"

    def run(self, once: bool = False) -> None:
        offset = None
        while True:
            updates = self._get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    callback = update.get("callback_query") or {}
                    user = callback.get("from") or {}
                    message = callback.get("message") or {}
                    chat = message.get("chat") or {}
                    response = self.handlers.handle_callback(callback.get("data", ""), user.get("id"))
                    self._answer_callback(callback.get("id"))
                    self._send_message(chat.get("id"), response.text, response.reply_markup)
                else:
                    message = update.get("message") or {}
                    chat = message.get("chat") or {}
                    user = message.get("from") or {}
                    text = message.get("text") or ""
                    response = self.handlers.handle_message(text, user.get("id"))
                    self._send_message(chat.get("id"), response.text, response.reply_markup)
            if once:
                return
            time.sleep(self.poll_interval_sec)

    def _get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        params = {"timeout": 20}
        if offset is not None:
            params["offset"] = offset
        response = requests.get(f"{self.base_url}/getUpdates", params=params, timeout=30)
        response.raise_for_status()
        return response.json().get("result", [])

    def _send_message(self, chat_id: int | str | None, text: str, reply_markup: dict | None = None) -> None:
        if chat_id is None:
            return
        payload = {"chat_id": chat_id, "text": text[:3900]}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10).raise_for_status()

    def _answer_callback(self, callback_query_id: str | None) -> None:
        if not callback_query_id:
            return
        requests.post(
            f"{self.base_url}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
            timeout=10,
        ).raise_for_status()


def run_telegram_bot(once: bool = False) -> None:
    config = load_telegram_config_from_env()
    handlers = TelegramHandlers(config)
    TelegramBot(config.token, handlers).run(once=once)
