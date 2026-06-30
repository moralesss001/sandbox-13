import pandas as pd

from src.live_research_engine import LiveResearchEngine
from src.runtime_status import RuntimeStatusStore


def _klines() -> pd.DataFrame:
    rows = []
    base_close_time = 1_700_000_000_000
    for index in range(20):
        close = 100 + index
        rows.append(
            {
                "open_time": base_close_time - (20 - index) * 60_000,
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 1,
                "close_time": base_close_time + index,
                "quote_asset_volume": 1,
                "number_of_trades": 1,
                "taker_buy_base_volume": 1,
                "taker_buy_quote_volume": 1,
                "ignore": 0,
            }
        )
    return pd.DataFrame(rows)


def test_live_research_runs_one_safe_iteration(monkeypatch, tmp_path):
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *args, **kwargs: _klines())
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    result = engine.run(["BTCUSDT"], "15m", max_iterations=1)

    assert result["signal_source"] == "research_simplified_live"
    assert store.read()["last_processed_candles"]["BTCUSDT:15m"]


def test_live_research_avoids_duplicate_closed_candles(monkeypatch, tmp_path):
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *args, **kwargs: _klines())
    monkeypatch.setattr("src.live_research_engine.time.sleep", lambda *_args, **_kwargs: None)
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    result = engine.run(["BTCUSDT"], "15m", interval_sec=1, max_iterations=2)

    assert len(result["events"]) == 15
    assert store.read()["last_processed_candles"]["BTCUSDT:15m"]
