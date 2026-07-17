from __future__ import annotations

import os
from dataclasses import dataclass

from .execution_safety import validate_api_mode


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    allowed_user_id: str
    allowed_chat_id: str | None = None
    read_only: bool = True
    api_mode: str = "paper"
    allow_real_orders: bool = False
    production_trading_enabled: bool = False

    def is_allowed_user(self, user_id: str | int | None) -> bool:
        return str(user_id) == str(self.allowed_user_id)

    def is_allowed_chat(self, chat_id: str | int | None) -> bool:
        expected = self.allowed_chat_id or self.allowed_user_id
        return str(chat_id) == str(expected)


def _truthy(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_telegram_config_from_env(env: dict[str, str] | None = None) -> TelegramConfig:
    source = env or os.environ
    token = source.get("TELEGRAM_BOT_TOKEN", "").strip()
    allowed_user_id = source.get("TELEGRAM_ALLOWED_USER_ID", "").strip()
    allowed_chat_id = source.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip() or allowed_user_id
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for Telegram control bot")
    if not allowed_user_id:
        raise RuntimeError("TELEGRAM_ALLOWED_USER_ID is required for Telegram control bot")

    config = TelegramConfig(
        token=token,
        allowed_user_id=allowed_user_id,
        allowed_chat_id=allowed_chat_id,
        read_only=_truthy(source.get("TELEGRAM_READ_ONLY"), default=True),
        api_mode=source.get("API_MODE", "paper").strip().lower(),
        allow_real_orders=_truthy(source.get("ALLOW_REAL_ORDERS"), default=False),
        production_trading_enabled=_truthy(source.get("PRODUCTION_TRADING_ENABLED"), default=False),
    )
    validate_api_mode(
        {
            "mode": config.api_mode,
            "allow_real_orders": config.allow_real_orders,
            "production_trading_enabled": config.production_trading_enabled,
        }
    )
    if not config.read_only:
        raise RuntimeError("Telegram control bot must run with TELEGRAM_READ_ONLY=true")
    return config
