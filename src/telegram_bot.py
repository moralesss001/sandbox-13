from __future__ import annotations

import time
import re
import threading
from pathlib import Path
from typing import Any

import requests

from .telegram_config import load_telegram_config_from_env
from .telegram_control import TelegramControlPanel
from .telegram_buttons import TelegramResponse
from .telegram_handlers import TelegramHandlers


class TelegramBot:
    def __init__(self, token: str, handlers: TelegramHandlers, poll_interval_sec: int = 3):
        self.token = token
        self.handlers = handlers
        self.poll_interval_sec = max(1, int(poll_interval_sec))
        self.base_url = f"https://api.telegram.org/bot{token}"

    def run(self, once: bool = False, stop_event=None) -> None:
        stop_event = stop_event if stop_event is not None else threading.Event()
        offset = None
        while not stop_event.is_set():
            try:
                updates = self._get_updates(offset)
            except requests.RequestException:
                if once:
                    raise
                stop_event.wait(self.poll_interval_sec)
                continue
            for update in updates:
                if stop_event.is_set():
                    return
                offset = update["update_id"] + 1
                cutoff = getattr(self, "cloud_started_at", None)
                if cutoff is not None and "callback_query" not in update:
                    message_time = (update.get("message") or {}).get("date", 0)
                    if message_time <= cutoff:
                        continue  # Never replay pre-restart run/approve requests.
                if "callback_query" in update:
                    callback = update.get("callback_query") or {}
                    user = callback.get("from") or {}
                    message = callback.get("message") or {}
                    chat = message.get("chat") or {}
                    try:
                        response = self.handlers.handle_callback(
                            callback.get("data", ""), user.get("id"), chat.get("id")
                        )
                    except OSError as exc:
                        response = self._storage_error_response(exc)
                    try:
                        self._answer_callback(callback.get("id"))
                        self._deliver_response(chat.get("id"), response)
                    except requests.RequestException:
                        pass  # Transport failure is not a confirmed delivery.
                else:
                    message = update.get("message") or {}
                    chat = message.get("chat") or {}
                    user = message.get("from") or {}
                    text = message.get("text") or ""
                    try:
                        if "document" in message:
                            if not self.handlers.strategy_authorized(user.get("id"), chat.get("id")):
                                response = TelegramResponse("Unauthorized user/chat.")
                            else:
                                raw = self._download_package(message["document"])
                                response = self.handlers.handle_document(raw, user.get("id"), chat.get("id"))
                        else:
                            response = self.handlers.handle_message(text, user.get("id"), chat.get("id"))
                    except (ValueError, KeyError, requests.RequestException):
                        response = TelegramResponse(
                            "Файл отклонён или не удалось скачать. Отправьте .json до 128 КиБ. Стратегия не запущена."
                            if isinstance(self.handlers, CloudPackageHandlers) else
                            "Package document rejected or download unavailable. No strategy started.")
                    except OSError as exc:
                        response = self._storage_error_response(exc)
                    try:
                        self._deliver_response(chat.get("id"), response)
                    except requests.RequestException:
                        pass
            if once:
                return
            stop_event.wait(self.poll_interval_sec)

    def _download_package(self, document):
        from .strategy_packages import MAX_BYTES
        if not isinstance(document, dict):
            raise ValueError("invalid document metadata")
        name, size, file_id = document.get("file_name"), document.get("file_size"), document.get("file_id")
        if not isinstance(name, str) or not name.lower().endswith(".json") or type(size) is not int or not 0 < size <= MAX_BYTES or not isinstance(file_id, str):
            raise ValueError("bounded JSON document required")
        response = requests.get(f"{self.base_url}/getFile", params={"file_id": file_id}, timeout=10, allow_redirects=False)
        response.raise_for_status()
        info = response.json()
        if info.get("ok") is not True:
            raise ValueError("getFile failed")
        path = info["result"]["file_path"]
        if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", path) or path.startswith("/") or any(p in {"", ".", ".."} for p in path.split("/")):
            raise ValueError("invalid Telegram file path")
        with requests.get(f"https://api.telegram.org/file/bot{self.token}/{path}", stream=True,
                          timeout=(5, 10), allow_redirects=False) as downloaded:
            if downloaded.status_code != 200:
                raise ValueError("file download failed")
            chunks, total, started = [], 0, time.monotonic()
            for chunk in downloaded.iter_content(chunk_size=8192):
                total += len(chunk)
                if total > MAX_BYTES or time.monotonic() - started > 20:
                    raise ValueError("document exceeds limits")
                chunks.append(chunk)
        return b"".join(chunks)

    def _storage_error_response(self, exc: OSError) -> TelegramResponse:
        if isinstance(self.handlers, CloudPackageHandlers):
            return TelegramResponse("Ошибка хранения. Выполнение действия не подтверждено. Проверьте состояние системы.")
        errno_value = getattr(exc, "errno", None)
        detail = f" errno={errno_value}" if errno_value is not None else ""
        return TelegramResponse(
            "Storage failure detected"
            + detail
            + ". The requested action was not completed. "
            "Telegram control remains online; check runtime diagnostics and mounted storage."
        )

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

    def _deliver_response(self, chat_id: int | str | None, response: TelegramResponse) -> None:
        if not response.documents:
            self._send_message(chat_id, response.text, response.reply_markup)
            return

        self._send_message(chat_id, response.text)
        sent: list[str] = []
        missing: list[str] = []
        for document in response.documents:
            try:
                delivered = self._send_document(chat_id, document)
            except (OSError, requests.RequestException):
                delivered = False
            name = Path(document).name
            (sent if delivered else missing).append(name)

        cloud_ui = isinstance(self.handlers, CloudPackageHandlers)
        lines = ["Отправка отчёта завершена." if cloud_ui else "Export completed.", "",
                 "Отправлено:" if cloud_ui else "Sent:"]
        lines.extend(f"- {name}" for name in sent)
        if not sent:
            lines.append("- ничего" if cloud_ui else "- none")
        if missing:
            lines.extend(["", "Не доставлено:" if cloud_ui else "Missing:"])
            lines.extend(f"- {name}" for name in missing)
        self._send_message(chat_id, "\n".join(lines), response.reply_markup)

    def _send_document(self, chat_id: int | str | None, path: str) -> bool:
        if chat_id is None:
            return False
        document_path = Path(path)
        if not document_path.exists() or not document_path.is_file() or document_path.is_symlink():
            return False
        with document_path.open("rb") as handle:
            response = requests.post(
                f"{self.base_url}/sendDocument",
                data={"chat_id": chat_id},
                files={"document": (document_path.name, handle)},
                timeout=30,
            )
            response.raise_for_status()
        try:
            return response.json().get("ok") is True
        except (AttributeError, ValueError):
            return False


class CloudPackageHandlers(TelegramHandlers):
    """Package commands only; the old research control queue is not opened."""
    def __init__(self, config, strategies):
        self.config = config
        self.strategies = strategies

    def handle_message(self, text, user_id, chat_id=None):
        from .telegram_strategy_lifecycle import COMMANDS, HELP
        if not self.strategy_authorized(user_id, chat_id):
            return TelegramResponse("Нет доступа для этого пользователя или чата.")
        text = (text or "").strip()
        command = text.split()[0].split("@")[0] if text else ""
        if command in {"/start", "/dashboard"}:
            return self.strategies.ui("ui:dashboard" if command == "/dashboard" else "ui:home", user_id, chat_id)
        if command in COMMANDS:
            return self.strategies.command(" ".join([command] + text.split()[1:]))
        if command == "/help":
            return TelegramResponse("Технические команды (резервный доступ):\n" + HELP,
                                    self.strategies._ui_home())
        return self.strategies.ui("ui:home", user_id, chat_id)

    def handle_document(self, raw, user_id, chat_id=None):
        if not self.strategy_authorized(user_id, chat_id):
            return TelegramResponse("Нет доступа для этого пользователя или чата.")
        return self.strategies.ui("ui:upload", user_id, chat_id, raw=raw)

    def handle_callback(self, data, user_id, chat_id=None):
        if not self.strategy_authorized(user_id, chat_id):
            return TelegramResponse("Нет доступа для этого пользователя или чата.")
        if isinstance(data, str) and data.startswith("ui:"):
            return self.strategies.ui(data, user_id, chat_id)
        return TelegramResponse("Старые кнопки отключены. Откройте /start.")


def run_telegram_bot(once: bool = False, data_root: str = "data", stop_event=None) -> None:
    from .cloud_release import enabled, preflight, receiver_guard
    if enabled():
        root = preflight(data_root)
        with receiver_guard(root):
            config = load_telegram_config_from_env()
            from .telegram_strategy_lifecycle import StrategyService
            strategies = StrategyService(root, stop_event=stop_event, stopped_startup=True)
            try:
                bot = TelegramBot(config.token, CloudPackageHandlers(config, strategies))
                bot.cloud_started_at = int(time.time())
                bot.run(once=once, stop_event=stop_event)
            finally:
                strategies.close(timeout=None)
        return
    config = load_telegram_config_from_env()
    from .telegram_strategy_lifecycle import StrategyService
    try:
        options = {"stop_event": stop_event} if stop_event is not None else {}
        strategies = StrategyService(Path(data_root) / "strategy_lifecycle_v1", **options)
    except Exception:
        # New package storage/ownership failure must not remove the old panel.
        strategies = None
    try:
        handlers = TelegramHandlers(config, control=TelegramControlPanel(data_root=data_root), strategies=strategies)
        options = {"stop_event": stop_event} if stop_event is not None else {}
        TelegramBot(config.token, handlers).run(once=once, **options)
    finally:
        if strategies is not None:
            strategies.close(timeout=None)
