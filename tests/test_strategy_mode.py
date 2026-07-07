from src.models import MarketContext
from src.strategy_mode import determine_strategy_mode


def test_no_trade_for_unclear_phase():
    decision = determine_strategy_mode(MarketContext(market_phase="unclear"), "US")
    assert decision.mode == "NO_TRADE"
    assert decision.reason == "unclear_or_transition_market"


def test_aggressive_trend_for_strong_session():
    decision = determine_strategy_mode(MarketContext(market_phase="TREND_UP"), "EUROPE")
    assert decision.mode == "AGGRESSIVE_TREND"


def test_safe_trend_for_weaker_session():
    decision = determine_strategy_mode(MarketContext(market_phase="trend"), "ASIA")
    assert decision.mode == "SAFE_TREND"
