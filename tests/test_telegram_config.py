import pytest

from src.telegram_config import load_telegram_config_from_env


def test_telegram_config_refuses_missing_token():
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        load_telegram_config_from_env({"TELEGRAM_ALLOWED_USER_ID": "123", "API_MODE": "paper"})


def test_telegram_config_refuses_missing_allowed_user():
    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_USER_ID"):
        load_telegram_config_from_env({"TELEGRAM_BOT_TOKEN": "token", "API_MODE": "paper"})


def test_telegram_config_requires_paper_mode():
    with pytest.raises(RuntimeError, match="Production trading is disabled"):
        load_telegram_config_from_env(
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_USER_ID": "123",
                "API_MODE": "production",
                "TELEGRAM_READ_ONLY": "true",
            }
        )


def test_telegram_config_accepts_read_only_paper():
    config = load_telegram_config_from_env(
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_ALLOWED_USER_ID": "123",
            "API_MODE": "paper",
            "TELEGRAM_READ_ONLY": "true",
            "ALLOW_REAL_ORDERS": "false",
        }
    )

    assert config.is_allowed_user("123")
    assert config.is_allowed_chat("123")
    assert config.read_only is True


def test_telegram_config_supports_separate_allowed_chat():
    config = load_telegram_config_from_env(
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_ALLOWED_USER_ID": "123",
            "TELEGRAM_ALLOWED_CHAT_ID": "456",
            "API_MODE": "paper",
        }
    )

    assert config.is_allowed_user("123")
    assert config.is_allowed_chat("456")
    assert not config.is_allowed_chat("123")
