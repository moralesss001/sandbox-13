from src.order_models import SignalCandidate
from src.shadow_gates import (
    attach_shadow_gate_metadata,
    market_mode_gate,
    pattern_against_long_gate,
    rsi_gate,
    sl_width_gate,
)


def _candidate(rsi=50, raw=None, pattern=None, sl_pct=0.015, score=90):
    return SignalCandidate(
        symbol="BTCUSDT",
        timeframe="15m",
        direction="LONG",
        entry=100,
        tp=102.25,
        sl=98.5,
        rsi=rsi,
        pattern=pattern,
        sl_pct=sl_pct,
        score=score,
        raw=raw or {},
    )


def test_rsi_gate_enforces_both_production_boundaries():
    assert rsi_gate(34.9).reason == "rsi_below_35"
    assert rsi_gate(35).would_allow is True
    assert rsi_gate(65).would_allow is True
    assert rsi_gate(65.1).reason == "rsi_above_65"


def test_pattern_against_long_gate_blocks_only_bearish_patterns():
    assert pattern_against_long_gate("Bearish Engulfing").would_block is True
    assert pattern_against_long_gate("Bullish Engulfing").would_allow is True
    assert pattern_against_long_gate(None).would_allow is True


def test_sl_width_gate_uses_strict_production_limits():
    assert sl_width_gate(0.00749).reason == "sl_too_tight_15m"
    assert sl_width_gate(0.0075).would_allow is True
    assert sl_width_gate(0.035).would_allow is True
    assert sl_width_gate(0.03501).reason == "sl_too_wide_15m"


def test_market_mode_gate_keeps_no_trade_as_analytics_only():
    result = market_mode_gate({"market_mode_15m": "NO_TRADE"})

    assert result.would_allow is True
    assert result.would_block is False
    assert result.reason == "market_mode_15m_no_trade"
    assert result.source == "analytics_only"
    assert result.severity == "analytics_only"


def test_candidate_carries_all_post_candidate_gate_metadata():
    candidate = attach_shadow_gate_metadata(
        _candidate(
            rsi=32,
            pattern="Bearish Pinbar",
            sl_pct=0.04,
            raw={"market_mode_15m": "NO_TRADE"},
        )
    )

    assert len(candidate.shadow_gates) == 4
    assert candidate.production_would_allow is False
    assert candidate.production_block_reasons == [
        "rsi_below_35",
        "bearish_pattern_against_long",
        "sl_too_wide_15m",
    ]
    assert candidate.raw["production_block_reasons"] == candidate.production_block_reasons
    market_gate = next(gate for gate in candidate.shadow_gates if gate["gate_name"] == "market_mode_15m_gate")
    assert market_gate["would_block"] is False


def test_market_mode_and_score_do_not_change_production_decision():
    candidate = attach_shadow_gate_metadata(
        _candidate(score=0, raw={"market_mode_15m": "NO_TRADE"})
    )

    assert candidate.production_would_allow is True
    assert candidate.production_block_reasons == []
