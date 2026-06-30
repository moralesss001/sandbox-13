from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TradeResult(str, Enum):
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    OPEN = "open"


class HypothesisDecisionType(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REDUCE_RISK = "REDUCE_RISK"


@dataclass
class SignalCandidate:
    symbol: str
    timeframe: str
    direction: str
    entry: float
    tp: float
    sl: float
    rr_ratio: float = 1.5
    created_at: str | None = None
    rsi: float | None = None
    atr_pct: float | None = None
    market_phase: str = "UNKNOWN"
    session: str = "UNKNOWN"
    setup_type: str = "UNKNOWN"
    trend_htf: str = "UNKNOWN"
    reason: str | None = None
    confidence_factors: Any = None
    signal_source: str = "unknown"
    source: str = "unknown"
    result: str | None = None
    historical_r: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Order:
    order_id: str
    hypothesis_id: str
    symbol: str
    timeframe: str
    direction: str
    entry_price: float
    tp: float
    sl: float
    position_size_usdt: float
    leverage: float
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Position:
    trade_id: str
    hypothesis_id: str
    symbol: str
    timeframe: str
    direction: str
    entry_time: str
    entry_price: float
    tp: float
    sl: float
    rr_ratio: float
    position_size_usdt: float
    leverage: float
    status: str = TradeStatus.OPEN.value
    reason: str | None = None
    market_phase: str = "UNKNOWN"
    session: str = "UNKNOWN"
    setup_type: str = "UNKNOWN"
    rsi: float | None = None
    atr_pct: float | None = None
    trend_htf: str = "UNKNOWN"
    source: str = "unknown"


@dataclass
class Trade(Position):
    exit_time: str | None = None
    exit_price: float | None = None
    result: str = TradeResult.OPEN.value
    r: float = 0.0
    pnl_usdt: float = 0.0
    fees_usdt: float = 0.0
    slippage_usdt: float = 0.0


@dataclass
class ExecutionResult:
    status: str
    trade: Trade | None = None
    reason: str | None = None


@dataclass
class PortfolioState:
    hypothesis_id: str
    balance: float
    equity: float
    open_positions: list[Position] = field(default_factory=list)
    closed_trades: list[Trade] = field(default_factory=list)
    max_drawdown_R: float = 0.0
    winrate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    net_R: float = 0.0
    max_loss_streak: int = 0


@dataclass
class HypothesisDecision:
    hypothesis_id: str
    decision: str
    block_reason: str | None = None
    size_multiplier: float = 1.0


def new_trade_id(hypothesis_id: str, symbol: str) -> str:
    return f"{hypothesis_id}-{symbol}-{uuid4().hex[:12]}"

