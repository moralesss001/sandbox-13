from src.gate_analytics import classify_gate_outcome, summarize_gate_outcomes


def test_gate_outcome_analytics_classifies_saved_from_loss():
    assert classify_gate_outcome({"production_would_allow": False, "r": -1}) == "gate_saved_from_loss"


def test_gate_outcome_analytics_classifies_missed_profit():
    assert classify_gate_outcome({"production_would_allow": False, "r": 1.5}) == "gate_missed_profit"


def test_gate_outcome_analytics_classifies_allowed_loss():
    assert classify_gate_outcome({"production_would_allow": True, "r": -1}) == "gate_allowed_loss"


def test_gate_outcome_analytics_classifies_allowed_profit():
    assert classify_gate_outcome({"production_would_allow": True, "r": 1.5}) == "gate_allowed_profit"


def test_gate_outcome_analytics_summarizes_empty_or_mixed_trades():
    assert summarize_gate_outcomes([]) == {
        "gate_saved_from_loss": 0,
        "gate_missed_profit": 0,
        "gate_allowed_loss": 0,
        "gate_allowed_profit": 0,
    }
    assert summarize_gate_outcomes(
        [
            {"production_would_allow": False, "r": -1},
            {"production_would_allow": False, "r": 1.5},
            {"production_would_allow": True, "r": -1},
            {"production_would_allow": True, "r": 1.5},
        ]
    ) == {
        "gate_saved_from_loss": 1,
        "gate_missed_profit": 1,
        "gate_allowed_loss": 1,
        "gate_allowed_profit": 1,
    }


def test_gate_outcome_analytics_parses_csv_boolean_strings():
    assert classify_gate_outcome({"production_would_allow": "False", "r": -1}) == "gate_saved_from_loss"
    assert classify_gate_outcome({"production_would_allow": "True", "r": 1.5}) == "gate_allowed_profit"
