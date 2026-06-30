from src.order_models import SignalCandidate
from src.paper_broker import PaperBroker
from src.portfolio import PaperPortfolio


def _signal() -> SignalCandidate:
    return SignalCandidate(
        symbol="BTCUSDT",
        timeframe="15m",
        direction="LONG",
        entry=100.0,
        tp=115.0,
        sl=90.0,
        rr_ratio=1.5,
        signal_source="test",
    )


def test_paper_broker_closes_take_profit():
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio, fee_rate=0, slippage_pct=0)
    broker.open_position(_signal())

    closed = broker.update_positions({"high": 116.0, "low": 99.0})

    assert len(closed) == 1
    assert closed[0].result == "win"
    assert closed[0].r == 1.5


def test_paper_broker_closes_stop_loss():
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio, fee_rate=0, slippage_pct=0)
    broker.open_position(_signal())

    closed = broker.update_positions({"high": 101.0, "low": 89.0})

    assert len(closed) == 1
    assert closed[0].result == "loss"
    assert closed[0].r == -1.0


def test_conservative_intrabar_policy_counts_sl_first():
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio, fee_rate=0, slippage_pct=0, intrabar_policy="conservative")
    broker.open_position(_signal())

    closed = broker.update_positions({"high": 116.0, "low": 89.0})

    assert len(closed) == 1
    assert closed[0].result == "loss"
    assert closed[0].exit_price == 90.0

