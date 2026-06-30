from __future__ import annotations

from typing import Any

from .execution_safety import assert_testnet_only


class TestnetBroker:
    __test__ = False

    def __init__(self, base_url: str, allow_testnet_orders: bool = False, confirmed: bool = False):
        self.base_url = base_url
        self.allow_testnet_orders = allow_testnet_orders
        self.confirmed = confirmed

    def _guard(self) -> None:
        assert_testnet_only(self.base_url, self.allow_testnet_orders, self.confirmed)

    def place_testnet_order(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self._guard()
        return {"status": "not_implemented", "mode": "testnet"}

    def cancel_testnet_order(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self._guard()
        return {"status": "not_implemented", "mode": "testnet"}

    def get_testnet_positions(self) -> dict[str, Any]:
        self._guard()
        return {"positions": []}

    def close_testnet_position(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self._guard()
        return {"status": "not_implemented", "mode": "testnet"}
