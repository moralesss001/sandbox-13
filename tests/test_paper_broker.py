from src.order_models import SignalCandidate
from src.paper_broker import PaperBroker
from src.portfolio import PaperPortfolio
from src.shadow_gates import attach_shadow_gate_metadata


def _signal(rsi: float = 50.0) -> SignalCandidate:
    return attach_shadow_gate_metadata(SignalCandidate(
        symbol="BTCUSDT",
        timeframe="15m",
        direction="LONG",
        entry=100.0,
        tp=115.0,
        sl=90.0,
        rr_ratio=1.5,
        rsi=rsi,
        signal_source="test",
    ))


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


def test_closed_trade_includes_shadow_gate_enrichment():
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio, fee_rate=0, slippage_pct=0)
    broker.open_position(_signal(rsi=32))

    closed = broker.update_positions({"high": 101.0, "low": 89.0})

    assert closed[0].production_would_allow is False
    assert closed[0].production_block_reasons == ["rsi_below_35"]
    assert closed[0].shadow_gate_block_reasons == ["rsi_below_35"]


def test_production_parity_fields_flow_to_position_and_closed_trade():
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio, fee_rate=0, slippage_pct=0)
    signal = _signal()
    signal.production_signal_id = "BTCUSDT:15m:1700000000000:LONG"
    signal.score = 88
    signal.pattern = "Bullish Engulfing"
    signal.supertrend_dir = "UP"
    signal.macd = True
    signal.volume = True
    signal.atr = 1.0
    signal.sl_pct = 0.015
    signal.risk_distance = 1.5
    signal.reward_distance = 2.25
    signal.actual_rr = 1.5
    signal.market_mode_pre = "NO_TRADE:flat_no_impulse_no_extreme"
    signal.market_mode_post = signal.market_mode_pre

    broker.open_position(signal)
    position = portfolio.open_positions[0]
    trade = broker.close_position(position, reason="TP", exit_price=position.tp)

    assert position.entry_price == signal.entry
    assert position.sl == signal.sl
    assert position.tp == signal.tp
    assert position.rr_ratio == signal.rr_ratio
    assert trade.production_signal_id == signal.production_signal_id
    assert trade.score == 88
    assert trade.risk_distance == 1.5
    assert trade.reward_distance == 2.25
    assert trade.actual_rr == 1.5
    assert trade.market_mode_pre == signal.market_mode_pre
