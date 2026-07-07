from __future__ import annotations

from .models import MarketContext, ModeDecision

UNCLEAR_PHASES = {"unclear", "transition"}


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def determine_risk_mode(context: MarketContext, session: str, strategy_mode: str) -> ModeDecision:
    market_phase = _norm(context.market_phase)
    if strategy_mode == "NO_TRADE":
        return ModeDecision("NO_RISK", "strategy_no_trade")
    if context.rsi_zone == "LOW" and market_phase in UNCLEAR_PHASES:
        return ModeDecision("NO_RISK", "low_rsi_unclear_or_transition")
    if context.volatility_state == "HIGH_VOL":
        return ModeDecision("REDUCED_RISK", "high_volatility")
    if session == "US" and market_phase in UNCLEAR_PHASES:
        return ModeDecision("NO_RISK", "us_unclear_or_transition")
    return ModeDecision("NORMAL_RISK", "default_normal_risk")
