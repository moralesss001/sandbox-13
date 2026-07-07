from src.hypothesis_runner import HypothesisRunner
from src.order_models import SignalCandidate


def test_each_hypothesis_gets_separate_portfolio():
    runner = HypothesisRunner(data_root="/tmp/crypto13_test_runner")

    assert "baseline_rr15" in runner.portfolios
    assert "ban_rsi_below_35" in runner.portfolios
    assert runner.portfolios["baseline_rr15"] is not runner.portfolios["ban_rsi_below_35"]


def test_hypothesis_replay_counts_baseline_and_filter():
    signal = SignalCandidate(
        symbol="BTCUSDT",
        timeframe="15m",
        direction="LONG",
        entry=100.0,
        tp=115.0,
        sl=90.0,
        rr_ratio=1.5,
        rsi=30.0,
        market_phase="unclear",
        session="EUROPE",
        setup_type="rebound",
        signal_source="journal_replay",
        result="loss",
    )
    runner = HypothesisRunner(data_root="/tmp/crypto13_test_runner")
    runner.process_signal(signal, close_from_history=True)
    metrics = runner.metrics()

    assert metrics["baseline_rr15"]["total_trades"] == 1
    assert metrics["baseline_rr15"]["net_R"] == -1.0
    assert metrics["ban_rsi_below_35"]["trades_blocked"] == 1
    assert metrics["ban_rsi_below_35"]["blocked_losses"] == 1

