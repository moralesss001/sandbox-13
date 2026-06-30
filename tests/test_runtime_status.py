from src.runtime_status import RuntimeStatusStore


def test_runtime_status_writes_and_reads(tmp_path):
    store = RuntimeStatusStore(tmp_path / "status.json")

    store.update(mode="paper", symbols=["BTCUSDT"], timeframe="15m")
    status = store.read()

    assert status["mode"] == "paper"
    assert status["symbols"] == ["BTCUSDT"]
    assert status["timeframe"] == "15m"
    assert status["updated_at"]


def test_runtime_status_appends_errors(tmp_path):
    store = RuntimeStatusStore(tmp_path / "status.json")

    store.append_error("temporary binance error")

    assert store.read()["errors"][0]["error"] == "temporary binance error"

