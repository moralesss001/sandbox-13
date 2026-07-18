from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
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
    candidate_id: str | None = None
    signal_id: str | None = None
    created_at: str | None = None
    rsi: float | None = None
    atr_pct: float | None = None
    market_phase: str = "UNKNOWN"
    session: str = "UNKNOWN"
    setup_type: str = "UNKNOWN"
    trend_htf: str = "UNKNOWN"
    production_signal_id: str | None = None
    score: int | None = None
    pattern: str | None = None
    supertrend_dir: str | None = None
    macd: bool | None = None
    volume: bool | None = None
    atr: float | None = None
    sl_pct: float | None = None
    risk_distance: float | None = None
    reward_distance: float | None = None
    actual_rr: float | None = None
    market_mode_pre: str | None = None
    market_mode_post: str | None = None
    reason: str | None = None
    confidence_factors: Any = None
    signal_source: str = "unknown"
    source: str = "unknown"
    candidate_source: str = "unknown"
    candidate_source_version: str = "unknown"
    is_placeholder: bool = False
    edge_conclusions_allowed: bool = False
    direction_support: str = "UNKNOWN"
    source_description: str = ""
    result: str | None = None
    historical_r: float | None = None
    shadow_gates: list[dict[str, Any]] = field(default_factory=list)
    production_would_allow: bool = True
    production_block_reasons: list[str] = field(default_factory=list)
    shadow_gate_block_reasons: list[str] = field(default_factory=list)
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
    candidate_id: str | None = None
    signal_id: str | None = None
    status: str = TradeStatus.OPEN.value
    reason: str | None = None
    market_phase: str = "UNKNOWN"
    session: str = "UNKNOWN"
    setup_type: str = "UNKNOWN"
    rsi: float | None = None
    atr_pct: float | None = None
    trend_htf: str = "UNKNOWN"
    production_signal_id: str | None = None
    score: int | None = None
    pattern: str | None = None
    supertrend_dir: str | None = None
    macd: bool | None = None
    volume: bool | None = None
    atr: float | None = None
    sl_pct: float | None = None
    risk_distance: float | None = None
    reward_distance: float | None = None
    actual_rr: float | None = None
    market_mode_pre: str | None = None
    market_mode_post: str | None = None
    source: str = "unknown"
    candidate_source: str = "unknown"
    candidate_source_version: str = "unknown"
    is_placeholder: bool = False
    edge_conclusions_allowed: bool = False
    direction_support: str = "UNKNOWN"
    source_description: str = ""
    shadow_gates: list[dict[str, Any]] = field(default_factory=list)
    production_would_allow: bool = True
    production_block_reasons: list[str] = field(default_factory=list)
    shadow_gate_block_reasons: list[str] = field(default_factory=list)


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


def ensure_candidate_id(signal: SignalCandidate) -> str:
    """Return a restart-stable identity for a live candle candidate."""
    if signal.candidate_id:
        return str(signal.candidate_id)
    raw = signal.raw or {}
    candle_time = next(
        (
            raw.get(field)
            for field in ("candle_close_time", "close_time", "candle_open_time", "open_time")
            if raw.get(field) is not None
        ),
        signal.created_at or "unknown_time",
    )
    material = "|".join(
        [
            str(signal.candidate_source or "unknown"),
            str(signal.candidate_source_version or "unknown"),
            signal.symbol.upper(),
            signal.timeframe.lower(),
            signal.direction.upper(),
            str(candle_time),
            str(signal.setup_type or "UNKNOWN").lower(),
        ]
    )
    signal.candidate_id = f"candidate-{sha256(material.encode('utf-8')).hexdigest()[:24]}"
    signal.signal_id = signal.signal_id or signal.candidate_id
    return signal.candidate_id


def hypothesis_signal_id(candidate_id: str, hypothesis_id: str) -> str:
    """Identify one candidate instance inside one paper hypothesis portfolio."""
    material = f"{candidate_id}|{hypothesis_id}"
    return f"signal-{sha256(material.encode('utf-8')).hexdigest()[:24]}"
