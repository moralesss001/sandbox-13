from src.runtime_status import RuntimeStatusStore


def test_runtime_status_writes_and_reads(tmp_path):
    store = RuntimeStatusStore(tmp_path / "status.json")

    store.update(mode="paper", symbols=["BTCUSDT"], timeframe="15m")
    status = store.read()

    assert status["mode"] == "paper"
    assert status["symbols"] == ["BTCUSDT"]
    assert status["timeframe"] == "15m"
    assert status["candidate_source"] == "simplified_placeholder"
    assert status["candidate_source_version"] == "v1"
    assert status["is_placeholder"] is True
    assert status["candidate_source_is_placeholder"] is True
    assert status["edge_conclusions_allowed"] is False
    assert status["candidate_source_warning"] == "technical smoke source only; do not use for edge conclusions"
    assert status["direction_support"] == "LONG_AND_SHORT"
    assert status["source_description"] == "MA/ATR simplified placeholder for technical live paper smoke testing only"
    assert status["live_direction_policy"] == "LONG_ONLY"
    assert status["updated_at"]


def test_runtime_status_appends_errors(tmp_path):
    store = RuntimeStatusStore(tmp_path / "status.json")

    store.append_error("temporary binance error")

    assert store.read()["errors"][0]["error"] == "temporary binance error"
