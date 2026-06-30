from src.models import MarketContext
from src.risk_mode import determine_risk_mode


def test_strategy_no_trade_maps_to_no_risk():
    decision = determine_risk_mode(MarketContext(market_phase="trend"), "US", "NO_TRADE")
    assert decision.mode == "NO_RISK"


def test_high_vol_reduces_risk():
    decision = determine_risk_mode(
        MarketContext(market_phase="trend", volatility_state="HIGH_VOL"),
        "EUROPE",
        "SAFE_TREND",
    )
    assert decision.mode == "REDUCED_RISK"


def test_default_normal_risk():
    decision = determine_risk_mode(
        MarketContext(market_phase="trend", volatility_state="NORMAL_VOL", rsi_zone="MID"),
        "EUROPE",
        "AGGRESSIVE_TREND",
    )
    assert decision.mode == "NORMAL_RISK"
