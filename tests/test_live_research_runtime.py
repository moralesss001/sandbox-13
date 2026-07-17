import pandas as pd

from src.live_research_engine import LiveResearchEngine
from src.runtime_status import RuntimeStatusStore


def _klines() -> pd.DataFrame:
    rows = []
    base_close_time = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000) - 60_000
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
    frame = _klines()
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *args, **kwargs: frame.copy())
    monkeypatch.setattr("src.live_research_engine.time.sleep", lambda *_args, **_kwargs: None)
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    result = engine.run(["BTCUSDT"], "15m", interval_sec=1, max_iterations=2)

    assert len(result["events"]) == 15
    assert store.read()["last_processed_candles"]["BTCUSDT:15m"]


def test_unavailable_symbol_does_not_stop_other_symbols(monkeypatch, tmp_path):
    requested = []

    def fetch(symbol, *_args, **_kwargs):
        requested.append(symbol)
        if symbol == "AGIXUSDT":
            raise RuntimeError("symbol unavailable")
        return _klines()

    monkeypatch.setattr("src.live_research_engine.get_latest_klines", fetch)
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    engine.run(["AGIXUSDT", "BTCUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert requested == ["AGIXUSDT", "BTCUSDT"]
    assert status["configured_symbols"] == ["AGIXUSDT", "BTCUSDT"]
    assert status["active_symbols"] == ["BTCUSDT"]
    assert status["unavailable_symbols"] == ["AGIXUSDT"]
    assert status["unavailable_symbol_reasons"] == {"AGIXUSDT": "market_data_error"}


def test_recovered_symbol_moves_from_unavailable_to_active(monkeypatch, tmp_path):
    attempts = {"AGIXUSDT": 0}

    def fetch(symbol, *_args, **_kwargs):
        if symbol == "AGIXUSDT":
            attempts[symbol] += 1
            if attempts[symbol] == 1:
                raise RuntimeError("temporarily unavailable")
        return _klines()

    monkeypatch.setattr("src.live_research_engine.get_latest_klines", fetch)
    monkeypatch.setattr("src.live_research_engine.time.sleep", lambda *_args, **_kwargs: None)
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    engine.run(["AGIXUSDT", "BTCUSDT"], "15m", max_iterations=2)
    status = store.read()

    assert status["active_symbols"] == ["AGIXUSDT", "BTCUSDT"]
    assert status["unavailable_symbols"] == []
    assert status["unavailable_symbol_reasons"] == {}


def test_internal_processing_error_does_not_mark_market_data_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *_args, **_kwargs: _klines())
    monkeypatch.setattr(
        "src.live_research_engine.LiveResearchEngine._save_live_market",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    engine.run(["BTCUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert status["active_symbols"] == ["BTCUSDT"]
    assert status["unavailable_symbols"] == []
    assert status["unavailable_symbol_reasons"] == {}
    assert status["errors"][-1]["error"] == "BTCUSDT 15m internal: OSError"


def test_malformed_symbol_candles_do_not_stop_remaining_universe(monkeypatch, tmp_path):
    malformed = _klines()
    malformed["close_time"] = "invalid"
    requested = []

    def fetch(symbol, *_args, **_kwargs):
        requested.append(symbol)
        return malformed if symbol == "AGIXUSDT" else _klines()

    monkeypatch.setattr("src.live_research_engine.get_latest_klines", fetch)
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    engine.run(["AGIXUSDT", "BTCUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert requested == ["AGIXUSDT", "BTCUSDT"]
    assert status["active_symbols"] == ["BTCUSDT"]
    assert status["unavailable_symbols"] == ["AGIXUSDT"]
    assert status["unavailable_symbol_reasons"] == {"AGIXUSDT": "malformed_candles"}


def test_exchange_eligibility_filters_absent_and_settling_symbols(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.live_research_engine.get_exchange_info",
        lambda **_kwargs: {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "contractType": "PERPETUAL",
                    "quoteAsset": "USDT",
                },
                {
                    "symbol": "AGIXUSDT",
                    "status": "SETTLING",
                    "contractType": "PERPETUAL",
                    "quoteAsset": "USDT",
                },
                {
                    "symbol": "ETHUSDT",
                    "status": "TRADING",
                    "contractType": "CURRENT_QUARTER",
                    "quoteAsset": "USDT",
                },
                {
                    "symbol": "BNBUSDT",
                    "status": "TRADING",
                    "contractType": "PERPETUAL",
                    "quoteAsset": "BUSD",
                },
            ]
        },
    )
    requested = []
    monkeypatch.setattr(
        "src.live_research_engine.get_latest_klines",
        lambda symbol, *_args, **_kwargs: requested.append(symbol) or _klines(),
    )
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    engine.run(["BTCUSDT", "AGIXUSDT", "MATICUSDT", "ETHUSDT", "BNBUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert requested == ["BTCUSDT"]
    assert status["configured_symbols"] == ["BTCUSDT", "AGIXUSDT", "MATICUSDT", "ETHUSDT", "BNBUSDT"]
    assert status["active_symbols"] == ["BTCUSDT"]
    assert status["unavailable_symbol_reasons"] == {
        "AGIXUSDT": "symbol_status_not_trading",
        "BNBUSDT": "symbol_quote_asset_mismatch",
        "ETHUSDT": "symbol_not_perpetual",
        "MATICUSDT": "symbol_absent_exchange_info",
    }


def test_stale_closed_candle_is_unavailable_without_candidate(monkeypatch, tmp_path):
    stale = _klines()
    stale["close_time"] = stale["close_time"] - 31 * 60 * 1000
    builds = []
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *_args, **_kwargs: stale)
    monkeypatch.setattr(
        "src.live_research_engine.LiveResearchEngine._build_signal",
        lambda *_args, **_kwargs: builds.append(True),
    )
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    result = engine.run(["BTCUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert builds == []
    assert result["events"] == []
    assert status["active_symbols"] == []
    assert status["unavailable_symbol_reasons"] == {"BTCUSDT": "stale_closed_candle"}


def test_closed_candle_exactly_thirty_minutes_old_is_active(monkeypatch, tmp_path):
    now_ms = 1_800_000_000_000
    frame = _klines()
    frame["close_time"] = [now_ms - 30 * 60 * 1000 - (len(frame) - index - 1) for index in range(len(frame))]
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *_args, **_kwargs: frame)
    monkeypatch.setattr("src.live_research_engine.LiveResearchEngine._now_ms", lambda _self: now_ms)
    monkeypatch.setattr("src.live_research_engine.LiveResearchEngine._build_signal", lambda *_args, **_kwargs: None)
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    engine.run(["BTCUSDT"], "15m", max_iterations=1)

    assert store.read()["active_symbols"] == ["BTCUSDT"]
    assert store.read()["unavailable_symbols"] == []


def test_exchange_info_is_requested_once_per_iteration(monkeypatch, tmp_path):
    calls = []

    def exchange_info(**_kwargs):
        calls.append(True)
        return {
            "symbols": [
                {
                    "symbol": symbol,
                    "status": "TRADING",
                    "contractType": "PERPETUAL",
                    "quoteAsset": "USDT",
                }
                for symbol in ["BTCUSDT", "ETHUSDT"]
            ]
        }

    monkeypatch.setattr("src.live_research_engine.get_exchange_info", exchange_info)
    monkeypatch.setattr("src.live_research_engine.get_latest_klines", lambda *_args, **_kwargs: _klines())
    monkeypatch.setattr("src.live_research_engine.time.sleep", lambda *_args, **_kwargs: None)
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    engine.run(["BTCUSDT", "ETHUSDT"], "15m", max_iterations=2)

    assert len(calls) == 2


def test_exchange_info_failure_fails_closed(monkeypatch, tmp_path):
    requested = []
    monkeypatch.setattr(
        "src.live_research_engine.get_exchange_info",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("exchange unavailable")),
    )
    monkeypatch.setattr(
        "src.live_research_engine.get_latest_klines",
        lambda symbol, *_args, **_kwargs: requested.append(symbol) or _klines(),
    )
    store = RuntimeStatusStore(tmp_path / "runtime/status.json")
    engine = LiveResearchEngine({"api": {"mode": "paper"}, "safety": {}}, data_root=tmp_path, status_store=store)

    result = engine.run(["BTCUSDT", "ETHUSDT"], "15m", max_iterations=1)
    status = store.read()

    assert requested == []
    assert result["events"] == []
    assert status["active_symbols"] == []
    assert status["unavailable_symbol_reasons"] == {
        "BTCUSDT": "exchange_info_request_failed",
        "ETHUSDT": "exchange_info_request_failed",
    }
