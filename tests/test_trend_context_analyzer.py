import pandas as pd

from src.trend_context_analyzer import (
    build_trend_context_analysis,
    htf_alignment,
    normalize_trend_htf,
    research_readiness,
)


def _df():
    return pd.DataFrame(
        {
            "market_phase": ["unclear", "unclear", "unclear", "range", "range"],
            "session_shadow": ["US", "US", "ASIA", "EUROPE", "EUROPE"],
            "setup_type": ["rebound", "rebound", "rebound", "unknown", "unknown"],
            "trend_htf": ["Short", "Short", "Long", "Long", "Neutral"],
            "direction": ["LONG", "LONG", "LONG", "LONG", "LONG"],
            "result_normalized": ["loss", "loss", "win", "win", "loss"],
            "r": [-1.0, -1.0, 1.0, 1.0, -1.0],
        }
    )


def test_normalize_trend_htf():
    assert normalize_trend_htf("Long") == "bullish"
    assert normalize_trend_htf("Short") == "bearish"
    assert normalize_trend_htf("Neutral") == "neutral"
    assert normalize_trend_htf("") == "unknown"


def test_htf_alignment():
    assert htf_alignment("LONG", "bullish") == "aligned"
    assert htf_alignment("LONG", "bearish") == "countertrend"
    assert htf_alignment("SHORT", "bearish") == "aligned"
    assert htf_alignment("LONG", "neutral") == "neutral"


def test_build_trend_context_analysis():
    analysis = build_trend_context_analysis(_df())

    assert "htf_breakdown" in analysis
    assert "phase_session_setup_trend" in analysis
    assert "alignment_analysis" in analysis
    bearish = analysis["htf_breakdown"][analysis["htf_breakdown"]["trend_htf_normalized"] == "bearish"].iloc[0]
    assert bearish["trades"] == 2
    assert bearish["net_R"] == -2.0


def test_research_readiness():
    low = research_readiness(37, pd.DataFrame(), pd.DataFrame())
    high = research_readiness(68, pd.DataFrame({"combination": ["x"]}), pd.DataFrame())

    assert low["decision_readiness"] == "LOW"
    assert high["decision_readiness"] == "HIGH"
