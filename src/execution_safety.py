from __future__ import annotations

from typing import Any


PRODUCTION_DISABLED_MESSAGE = "Production trading is disabled in Crypto13Research"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def assert_not_production(config: dict[str, Any] | None = None) -> None:
    config = config or {}
    mode = str(config.get("mode", config.get("api_mode", "paper"))).lower()
    if mode in {"production", "prod", "live", "real"}:
        raise RuntimeError(PRODUCTION_DISABLED_MESSAGE)
    if _truthy(config.get("production_trading_enabled", False)) or _truthy(config.get("allow_real_orders", False)):
        raise RuntimeError(PRODUCTION_DISABLED_MESSAGE)


def assert_no_real_orders(config: dict[str, Any] | None = None) -> None:
    config = config or {}
    if _truthy(config.get("allow_real_orders", False)):
        raise RuntimeError(PRODUCTION_DISABLED_MESSAGE)
    assert_not_production(config)


def assert_testnet_only(base_url: str, allow_testnet_orders: bool = False, confirmed: bool = False) -> None:
    lowered = str(base_url).lower()
    if "demo" not in lowered and "testnet" not in lowered:
        raise RuntimeError("Testnet trading endpoints must use demo/testnet base URL")
    if not allow_testnet_orders:
        raise RuntimeError("Testnet orders are disabled: ALLOW_TESTNET_ORDERS=false")
    if not confirmed:
        raise RuntimeError("Testnet order requires --confirm-testnet-order")


def validate_api_mode(config: dict[str, Any] | None = None) -> str:
    config = config or {}
    mode = str(config.get("mode", config.get("api_mode", "paper"))).lower()
    if mode == "paper":
        assert_no_real_orders(config)
        return mode
    if mode == "testnet":
        assert_no_real_orders(config)
        return mode
    raise RuntimeError(PRODUCTION_DISABLED_MESSAGE)

