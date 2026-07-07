from src.order_models import Trade
from src.portfolio import PaperPortfolio


def _trade(r: float) -> Trade:
    return Trade(
        trade_id=f"t-{r}",
        hypothesis_id="h",
        symbol="BTCUSDT",
        timeframe="15m",
        direction="LONG",
        entry_time="2026-06-01T00:00:00Z",
        entry_price=100.0,
        tp=115.0,
        sl=90.0,
        rr_ratio=1.5,
        position_size_usdt=100.0,
        leverage=10.0,
        status="CLOSED",
        result="win" if r > 0 else "loss",
        r=r,
        pnl_usdt=100.0 * r,
    )


def test_portfolio_metrics_are_calculated():
    portfolio = PaperPortfolio("h")
    portfolio.add_closed_trade(_trade(1.5))
    portfolio.add_closed_trade(_trade(-1.0))
    metrics = portfolio.metrics(baseline_net_R=-1.0)

    assert metrics["total_trades"] == 2
    assert metrics["wins"] == 1
    assert metrics["losses"] == 1
    assert metrics["net_R"] == 0.5
    assert metrics["profit_factor"] == 1.5
    assert metrics["expectancy"] == 0.25
