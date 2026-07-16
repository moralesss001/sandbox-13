from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .order_models import (
    ExecutionResult,
    Position,
    SignalCandidate,
    Trade,
    ensure_candidate_id,
    hypothesis_signal_id,
    new_trade_id,
)
from .portfolio import PaperPortfolio


class PaperBroker:
    def __init__(
        self,
        portfolio: PaperPortfolio,
        position_size_usdt: float = 100.0,
        leverage: float = 10.0,
        fee_rate: float = 0.0004,
        slippage_pct: float = 0.0005,
        intrabar_policy: str = "conservative",
        known_closed_signal_ids: set[str] | None = None,
    ):
        self.portfolio = portfolio
        self.position_size_usdt = float(position_size_usdt)
        self.leverage = float(leverage)
        self.fee_rate = float(fee_rate)
        self.slippage_pct = float(slippage_pct)
        self.intrabar_policy = intrabar_policy
        self.known_closed_signal_ids = known_closed_signal_ids if known_closed_signal_ids is not None else set()

    def open_position(self, signal: SignalCandidate, size_multiplier: float = 1.0) -> ExecutionResult:
        candidate_id = ensure_candidate_id(signal)
        signal_id = hypothesis_signal_id(candidate_id, self.portfolio.hypothesis_id)
        if signal_id in self.known_closed_signal_ids:
            return ExecutionResult(status="DUPLICATE", reason="signal_already_closed")
        if any(position.signal_id == signal_id for position in self.portfolio.open_positions):
            return ExecutionResult(status="DUPLICATE", reason="signal_already_open")
        size = self.position_size_usdt * max(0.0, float(size_multiplier))
        position = Position(
            trade_id=new_trade_id(self.portfolio.hypothesis_id, signal.symbol),
            hypothesis_id=self.portfolio.hypothesis_id,
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            direction=signal.direction.upper(),
            entry_time=signal.created_at or datetime.now(timezone.utc).isoformat(),
            entry_price=float(signal.entry),
            tp=float(signal.tp),
            sl=float(signal.sl),
            rr_ratio=float(signal.rr_ratio or 1.5),
            position_size_usdt=size,
            leverage=self.leverage,
            candidate_id=candidate_id,
            signal_id=signal_id,
            reason=signal.reason,
            market_phase=signal.market_phase,
            session=signal.session,
            setup_type=signal.setup_type,
            rsi=signal.rsi,
            atr_pct=signal.atr_pct,
            trend_htf=signal.trend_htf,
            source=signal.signal_source,
            candidate_source=signal.candidate_source,
            candidate_source_version=signal.candidate_source_version,
            is_placeholder=signal.is_placeholder,
            edge_conclusions_allowed=signal.edge_conclusions_allowed,
            direction_support=signal.direction_support,
            source_description=signal.source_description,
            shadow_gates=signal.shadow_gates,
            production_would_allow=signal.production_would_allow,
            production_block_reasons=signal.production_block_reasons,
            shadow_gate_block_reasons=signal.shadow_gate_block_reasons,
        )
        if not self.portfolio.add_open_position(position):
            return ExecutionResult(status="DUPLICATE", reason="signal_already_open")
        return ExecutionResult(status="OPENED", trade=None, reason=None)

    def update_positions(self, current_candle: dict[str, Any], symbol: str | None = None) -> list[Trade]:
        closed: list[Trade] = []
        for position in list(self.portfolio.open_positions):
            if symbol and position.symbol.upper() != symbol.upper():
                continue
            exit_price, reason = self._resolve_exit(position, current_candle)
            if exit_price is not None:
                closed.append(self.close_position(position, reason=reason, exit_price=exit_price))
        return closed

    def close_position(self, position: Position, reason: str, exit_price: float | None = None) -> Trade:
        price = float(exit_price if exit_price is not None else position.entry_price)
        r_value = self._calculate_r(position, price, reason)
        notional = position.position_size_usdt * position.leverage
        pnl = position.position_size_usdt * r_value
        fees = notional * self.fee_rate * 2
        slippage = notional * self.slippage_pct
        payload = dict(position.__dict__)
        payload.pop("status", None)
        trade = Trade(
            **payload,
            status="CLOSED",
            exit_time=datetime.now(timezone.utc).isoformat(),
            exit_price=price,
            result="win" if r_value > 0 else "loss" if r_value < 0 else "breakeven",
            r=r_value,
            pnl_usdt=pnl,
            fees_usdt=fees,
            slippage_usdt=slippage,
        )
        self.portfolio.remove_open_position(position)
        self.portfolio.add_closed_trade(trade)
        if trade.signal_id:
            self.known_closed_signal_ids.add(trade.signal_id)
        return trade

    def get_open_positions(self) -> list[Position]:
        return list(self.portfolio.open_positions)

    def get_closed_trades(self) -> list[Trade]:
        return list(self.portfolio.closed_trades)

    def _resolve_exit(self, position: Position, candle: dict[str, Any]) -> tuple[float | None, str]:
        high = float(candle["high"])
        low = float(candle["low"])
        direction = position.direction.upper()
        if direction == "LONG":
            hit_tp = high >= position.tp
            hit_sl = low <= position.sl
        else:
            hit_tp = low <= position.tp
            hit_sl = high >= position.sl

        if hit_tp and hit_sl:
            if self.intrabar_policy == "conservative":
                return position.sl, "SL_CONSERVATIVE_INTRABAR"
            return position.tp, "TP_INTRABAR"
        if hit_sl:
            return position.sl, "SL"
        if hit_tp:
            return position.tp, "TP"
        return None, "OPEN"

    def _calculate_r(self, position: Position, exit_price: float, reason: str) -> float:
        if reason.startswith("SL"):
            return -1.0
        if reason.startswith("TP"):
            return float(position.rr_ratio)
        risk = abs(position.entry_price - position.sl)
        if risk == 0:
            return 0.0
        if position.direction.upper() == "LONG":
            return (exit_price - position.entry_price) / risk
        return (position.entry_price - exit_price) / risk
