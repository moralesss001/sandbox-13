import pytest

from src.execution_safety import (
    PRODUCTION_DISABLED_MESSAGE,
    assert_no_real_orders,
    assert_testnet_only,
    validate_api_mode,
)
from src.testnet_broker import TestnetBroker


def test_production_trading_impossible():
    with pytest.raises(RuntimeError, match=PRODUCTION_DISABLED_MESSAGE):
        validate_api_mode({"mode": "production"})


def test_real_orders_impossible():
    with pytest.raises(RuntimeError, match=PRODUCTION_DISABLED_MESSAGE):
        assert_no_real_orders({"mode": "paper", "allow_real_orders": True})


def test_testnet_order_requires_flag_and_confirmation():
    with pytest.raises(RuntimeError, match="ALLOW_TESTNET_ORDERS=false|disabled"):
        TestnetBroker("https://demo-fapi.binance.com").place_testnet_order()

    with pytest.raises(RuntimeError, match="confirm"):
        assert_testnet_only("https://demo-fapi.binance.com", allow_testnet_orders=True, confirmed=False)


def test_testnet_rejects_production_base_url():
    with pytest.raises(RuntimeError, match="demo/testnet"):
        assert_testnet_only("https://fapi.binance.com", allow_testnet_orders=True, confirmed=True)

