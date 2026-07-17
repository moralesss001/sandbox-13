import pytest

from src.universe import CONTRACT_UNIVERSE


@pytest.fixture(autouse=True)
def eligible_contract_exchange_info(monkeypatch):
    payload = {
        "symbols": [
            {
                "symbol": symbol,
                "status": "TRADING",
                "contractType": "PERPETUAL",
                "quoteAsset": "USDT",
            }
            for symbol in CONTRACT_UNIVERSE
        ]
    }
    monkeypatch.setattr("src.live_research_engine.get_exchange_info", lambda **_kwargs: payload)
