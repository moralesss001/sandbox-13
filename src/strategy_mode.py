from __future__ import annotations

from .models import MarketContext, ModeDecision

NO_TRADE_PHASES = {"unclear", "transition", "no_trade"}
TREND_PHASES = {"trend", "trend_up"}
RANGE_PHASES = {"range"}
STRONG_SESSIONS = {"US", "EUROPE", "OVERLAP"}


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def determine_strategy_mode(context: MarketContext, session: str) -> ModeDecision:
    market_phase = _norm(context.market_phase)
    if market_phase in NO_TRADE_PHASES:
        return ModeDecision("NO_TRADE", "unclear_or_transition_market")
    if market_phase in TREND_PHASES and session in STRONG_SESSIONS:
        return ModeDecision("AGGRESSIVE_TREND", "trend_session_ok")
    if market_phase in TREND_PHASES:
        return ModeDecision("SAFE_TREND", "trend_but_weaker_session")
    if market_phase in RANGE_PHASES:
        return ModeDecision("RANGE_ONLY", "range_market")
    return ModeDecision("OBSERVE_ONLY", "unknown_context")
