from src.session_classifier import normalize_session


def test_normalize_session_labels():
    assert normalize_session("EU") == "EUROPE"
    assert normalize_session("EUROPE") == "EUROPE"
    assert normalize_session("US") == "US"
    assert normalize_session("EU_US") == "OVERLAP"
    assert normalize_session("ASIA") == "ASIA"
