from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarketContext:
    rsi_zone: str = "UNKNOWN"
    volatility_state: str = "UNKNOWN"
    market_phase: str = "UNKNOWN"
    setup_type: str = "UNKNOWN"
    trend_htf: str = "UNKNOWN"
    impulse_before_entry: Any = None
    reason: str | None = None
    confidence_factors: Any = None
    rr_ratio: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ModeDecision:
    mode: str
    reason: str
