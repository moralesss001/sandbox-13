from src.order_models import Trade
from src.portfolio import PaperPortfolio
from src.research5_reporting import (
    _hypothesis_table,
    _trade_metrics,
    research_005_report_sections,
)


def _trade(index, *, profile, confidence, zone, session, phase, symbol, r):
    return Trade(
        trade_id=f"trade-{index}", hypothesis_id="baseline_rr15", symbol=symbol,
        timeframe="15m", direction="LONG", entry_time="2026-08-13T00:00:00Z",
        entry_price=100, tp=103, sl=98, rr_ratio=1.5, position_size_usdt=100,
        leverage=10, market_profile_v1=profile, market_profile_confidence=confidence,
        rsi_zone=zone, session=session, market_phase=phase, status="CLOSED", r=r,
        result="win" if r > 0 else "loss",
    )


def test_research_005_report_contains_required_breakdowns():
    baseline = PaperPortfolio("baseline_rr15")
    baseline.add_closed_trade(_trade(1, profile="REBOUND", confidence="HIGH", zone="<35", session="US", phase="range", symbol="BTCUSDT", r=1.5))
    baseline.add_closed_trade(_trade(2, profile="DEFENSIVE", confidence="MEDIUM", zone="40-65", session="EUROPE", phase="range", symbol="ETHUSDT", r=-1))
    metrics = {
        "baseline_rr15": baseline.metrics(),
        "block_multiple_reasons": {**baseline.metrics(), "hypothesis_id": "block_multiple_reasons"},
    }
    text = research_005_report_sections({"baseline_rr15": baseline}, metrics)
    for heading in (
        "Market Profile", "Profile confidence", "RSI zone", "Interaction hypotheses",
        "Production block attribution", "Session x Market Profile",
        "Market phase x Market Profile", "Symbol concentration",
    ):
        assert heading in text
    assert "REBOUND" in text
    assert "BTCUSDT" in text



def test_trade_metrics_mixed_wins_and_losses():
    trades = [
        _trade(10, profile="REBOUND", confidence="HIGH", zone="35-40", session="US", phase="range", symbol="BTCUSDT", r=1.5),
        _trade(11, profile="REBOUND", confidence="HIGH", zone="35-40", session="US", phase="range", symbol="BTCUSDT", r=1.5),
        _trade(12, profile="REBOUND", confidence="HIGH", zone="35-40", session="US", phase="range", symbol="BTCUSDT", r=-1),
    ]
    assert _trade_metrics(trades) == {
        "N": 3, "wins": 2, "losses": 1, "WR": 66.67,
        "net_R": 2.0, "gross_profit_R": 3.0, "gross_loss_R": 1.0,
        "expectancy_R": 0.666667, "profit_factor": 3.0,
    }


def test_trade_metrics_only_wins_use_na_profit_factor():
    trades = [
        _trade(20, profile="REBOUND", confidence="HIGH", zone="35-40", session="US", phase="range", symbol="BTCUSDT", r=1),
        _trade(21, profile="REBOUND", confidence="HIGH", zone="35-40", session="US", phase="range", symbol="BTCUSDT", r=1.5),
    ]
    metrics = _trade_metrics(trades)
    assert metrics["net_R"] == 2.5
    assert metrics["gross_profit_R"] == 2.5
    assert metrics["gross_loss_R"] == 0.0
    assert metrics["profit_factor"] is None


def test_trade_metrics_only_losses_and_empty_bucket():
    losses = [
        _trade(30, profile="DEFENSIVE", confidence="MEDIUM", zone="40-65", session="ASIA", phase="range", symbol="ETHUSDT", r=-1),
        _trade(31, profile="DEFENSIVE", confidence="MEDIUM", zone="40-65", session="ASIA", phase="range", symbol="ETHUSDT", r=-1),
    ]
    assert _trade_metrics(losses) == {
        "N": 2, "wins": 0, "losses": 2, "WR": 0.0,
        "net_R": -2.0, "gross_profit_R": 0, "gross_loss_R": 2.0,
        "expectancy_R": -1.0, "profit_factor": 0.0,
    }
    assert _trade_metrics([]) == {
        "N": 0, "wins": 0, "losses": 0, "WR": 0.0,
        "net_R": 0, "gross_profit_R": 0, "gross_loss_R": 0,
        "expectancy_R": 0.0, "profit_factor": None,
    }


def test_all_report_tables_use_explicit_r_semantics_and_na_pf():
    baseline = PaperPortfolio("baseline_rr15")
    baseline.add_closed_trade(
        _trade(40, profile="REBOUND", confidence="HIGH", zone="35-40", session="US", phase="range", symbol="BTCUSDT", r=1.5)
    )
    metrics = {
        "baseline_rr15": baseline.metrics(),
        "block_multiple_reasons": {**baseline.metrics(), "hypothesis_id": "block_multiple_reasons"},
    }
    text = research_005_report_sections({"baseline_rr15": baseline}, metrics)
    assert "gross_R" not in text
    assert text.count("net_R") >= 7
    assert text.count("gross_profit_R") >= 7
    assert text.count("gross_loss_R") >= 7
    assert text.count("profit_factor") >= 7
    assert "N/A" in text

    hypothesis_text = _hypothesis_table(metrics)
    assert "gross_R" not in hypothesis_text
    assert "net_R" in hypothesis_text
    assert "N/A" in hypothesis_text
