import pandas as pd

from src.production_like_raw_source import production_like_raw_signal_from_klines


def _klines(kind: str = "up", rows: int = 80) -> pd.DataFrame:
    data = []
    price = 100.0
    for index in range(rows):
        if kind == "down":
            price -= 0.35
        elif kind == "flat":
            price += 0.01 if index % 2 == 0 else -0.01
        else:
            price += 0.25
        open_price = price - 0.08
        close_price = price
        high = max(open_price, close_price) + 0.2
        low = min(open_price, close_price) - 0.2
        data.append(
            {
                "open_time": 1_700_000_000_000 + index * 900_000,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close_price,
                "volume": 100 + index,
                "close_time": 1_700_000_899_999 + index * 900_000,
            }
        )
    return pd.DataFrame(data)


def test_production_like_raw_emits_long_only_with_required_metadata():
    signal = production_like_raw_signal_from_klines("btcusdt", "15m", _klines("up"))

    assert signal is not None
    assert signal.symbol == "BTCUSDT"
    assert signal.direction == "LONG"
    assert signal.candidate_source == "production_like_raw"
    assert signal.candidate_source_version == "v1"
    assert signal.is_placeholder is False
    assert signal.edge_conclusions_allowed is False
    assert signal.direction_support == "LONG_ONLY"
    assert signal.source_description == (
        "Production-like raw LONG candidate source before hard-gate rejection for sandbox research"
    )


def test_score_is_analytics_only_and_low_score_does_not_reject_candidate():
    signal = production_like_raw_signal_from_klines("BTCUSDT", "15m", _klines("down"))

    assert signal is not None
    assert signal.raw["score_analytics_only"] is True
    assert signal.raw["score_used_as_gate"] is False
    assert signal.raw["score_label"] == "LOW_SCORE"
    assert signal.direction == "LONG"


def test_shadow_rsi_gate_can_block_without_removing_candidate():
    signal = production_like_raw_signal_from_klines("BTCUSDT", "15m", _klines("down"))

    assert signal is not None
    assert signal.production_would_allow is False
    assert "rsi_below_35" in signal.production_block_reasons
    assert signal.direction == "LONG"


def test_market_mode_is_preserved_as_analytics_without_blocking_candidate():
    signal = production_like_raw_signal_from_klines("BTCUSDT", "15m", _klines("flat"))

    assert signal is not None
    assert signal.raw["market_mode_15m"].startswith("NO_TRADE")
    assert signal.production_would_allow is True
    assert "market_mode_15m_no_trade" not in signal.production_block_reasons
    market_gate = next(gate for gate in signal.shadow_gates if gate["gate_name"] == "market_mode_15m_gate")
    assert market_gate["severity"] == "analytics_only"
    assert market_gate["value"].startswith("NO_TRADE")


def test_unsupported_timeframe_emits_no_candidate():
    assert production_like_raw_signal_from_klines("BTCUSDT", "5m", _klines("up")) is None
