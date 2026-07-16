from __future__ import annotations

from dataclasses import dataclass, field

from .order_models import PortfolioState, Trade


@dataclass
class PaperPortfolio:
    hypothesis_id: str
    starting_balance_usdt: float = 1000.0
    balance: float | None = None
    open_positions: list = field(default_factory=list)
    closed_trades: list[Trade] = field(default_factory=list)
    equity_curve_R: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.balance is None:
            self.balance = float(self.starting_balance_usdt)

    def add_open_position(self, position) -> bool:
        identity = getattr(position, "signal_id", None) or getattr(position, "trade_id", None)
        if identity and any(
            (getattr(item, "signal_id", None) or getattr(item, "trade_id", None)) == identity
            for item in self.open_positions
        ):
            return False
        self.open_positions.append(position)
        return True

    def remove_open_position(self, position) -> None:
        self.open_positions = [item for item in self.open_positions if item.trade_id != position.trade_id]

    def add_closed_trade(self, trade: Trade) -> bool:
        identity = getattr(trade, "signal_id", None) or getattr(trade, "trade_id", None)
        if identity and any(
            (getattr(item, "signal_id", None) or getattr(item, "trade_id", None)) == identity
            for item in self.closed_trades
        ):
            return False
        self.closed_trades.append(trade)
        self.balance = float(self.balance or 0.0) + trade.pnl_usdt - trade.fees_usdt - trade.slippage_usdt
        self.equity_curve_R.append(self.net_R)
        return True

    @property
    def wins(self) -> list[Trade]:
        return [trade for trade in self.closed_trades if trade.r > 0]

    @property
    def losses(self) -> list[Trade]:
        return [trade for trade in self.closed_trades if trade.r < 0]

    @property
    def net_R(self) -> float:
        return float(sum(trade.r for trade in self.closed_trades))

    @property
    def gross_profit_R(self) -> float:
        return float(sum(trade.r for trade in self.closed_trades if trade.r > 0))

    @property
    def gross_loss_R(self) -> float:
        return abs(float(sum(trade.r for trade in self.closed_trades if trade.r < 0)))

    @property
    def profit_factor(self) -> float:
        loss = self.gross_loss_R
        if loss == 0:
            return self.gross_profit_R if self.gross_profit_R else 0.0
        return self.gross_profit_R / loss

    @property
    def expectancy(self) -> float:
        if not self.closed_trades:
            return 0.0
        return self.net_R / len(self.closed_trades)

    @property
    def winrate(self) -> float:
        if not self.closed_trades:
            return 0.0
        return len(self.wins) / len(self.closed_trades) * 100

    @property
    def max_loss_streak(self) -> int:
        current = 0
        best = 0
        for trade in self.closed_trades:
            if trade.r < 0:
                current += 1
                best = max(best, current)
            else:
                current = 0
        return best

    @property
    def max_drawdown_R(self) -> float:
        peak = 0.0
        running = 0.0
        max_dd = 0.0
        for trade in self.closed_trades:
            running += trade.r
            peak = max(peak, running)
            max_dd = max(max_dd, peak - running)
        return max_dd

    def to_state(self) -> PortfolioState:
        return PortfolioState(
            hypothesis_id=self.hypothesis_id,
            balance=float(self.balance or 0.0),
            equity=float(self.balance or 0.0),
            open_positions=list(self.open_positions),
            closed_trades=list(self.closed_trades),
            max_drawdown_R=self.max_drawdown_R,
            winrate=self.winrate,
            profit_factor=self.profit_factor,
            expectancy=self.expectancy,
            net_R=self.net_R,
            max_loss_streak=self.max_loss_streak,
        )

    def metrics(self, baseline_net_R: float | None = None) -> dict:
        total = len(self.closed_trades)
        wins = len(self.wins)
        losses = len(self.losses)
        avg_win = self.gross_profit_R / wins if wins else 0.0
        avg_loss = -(self.gross_loss_R / losses) if losses else 0.0
        baseline = self.net_R if baseline_net_R is None else baseline_net_R
        candidate = (
            total >= 30
            and self.profit_factor > 1.2
            and self.expectancy > 0
            and self.net_R > baseline
            and self.max_drawdown_R <= max(5.0, abs(self.net_R) * 0.75)
        )
        return {
            "hypothesis_id": self.hypothesis_id,
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "winrate": self.winrate,
            "gross_profit_R": self.gross_profit_R,
            "gross_loss_R": self.gross_loss_R,
            "profit_factor": self.profit_factor,
            "expectancy": self.expectancy,
            "net_R": self.net_R,
            "max_drawdown_R": self.max_drawdown_R,
            "max_loss_streak": self.max_loss_streak,
            "avg_win_R": avg_win,
            "avg_loss_R": avg_loss,
            "candidate_for_testnet": candidate,
        }
