import pandas as pd

from src.combination_analyzer import (
    build_combination_analysis,
    combination_stats,
    find_positive_combinations,
    find_toxic_combinations,
)


def _df():
    return pd.DataFrame(
        {
            "market_phase": ["unclear", "unclear", "unclear", "range", "range", "range"],
            "session_shadow": ["US", "US", "US", "EUROPE", "EUROPE", "EUROPE"],
            "setup_type": ["rebound", "rebound", "rebound", "unknown", "unknown", "unknown"],
            "rsi_zone": ["LOW", "LOW", "MID", "MID", "MID", "HIGH"],
            "result_normalized": ["loss", "loss", "win", "win", "win", "loss"],
            "r": [-1.0, -1.0, 1.0, 1.0, 1.0, -1.0],
            "rr_ratio": [1.5, 1.5, 1.5, 1.0, 1.0, 1.0],
        }
    )


def test_combination_stats_level_3():
    stats = combination_stats(_df(), ["market_phase", "session_shadow", "setup_type"])

    row = stats[stats["combination"] == "unclear + US + rebound"].iloc[0]
    assert row["trades"] == 3
    assert row["wins"] == 1
    assert row["losses"] == 2
    assert round(row["winrate"], 2) == 33.33
    assert row["net_R"] == -1.0


def test_find_toxic_and_positive_combinations():
    toxic = find_toxic_combinations(_df())
    positive = find_positive_combinations(_df())

    assert toxic.iloc[0]["combination"] == "unclear + US + rebound"
    assert positive.iloc[0]["combination"] == "range + EUROPE + unknown"


def test_build_combination_analysis_includes_rsi_and_rr():
    analysis = build_combination_analysis(_df())

    assert "phase_session" in analysis
    assert "phase_session_setup" in analysis
    assert "phase_rsi" in analysis
    assert "phase_session_rsi" in analysis
    assert "rr_ratio" in analysis
    assert not analysis["rr_ratio"].empty
