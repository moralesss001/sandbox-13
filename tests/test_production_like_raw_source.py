import pandas as pd
import pytest

from src.hypothesis_runner import HypothesisRunner
from src.production_like_raw_source import production_like_raw_signal_from_klines
from src.production_parity_15m import (
    ParityEvaluation,
    compute_rsi,
    evaluate_15m_long_candidate,
)


START_15M = 1_700_000_000_000
START_1H = 1_699_700_000_000


def _klines_15m(
    rows: int = 80,
    *,
    price: float = 100.0,
    candle_range: float = 1.0,
    last_volume: float = 200.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "open_time": START_15M + index * 900_000,
                "open": price - 0.2,
                "high": price + candle_range / 2,
                "low": price - candle_range / 2,
                "close": price,
                "volume": last_volume if index == rows - 1 else 100.0,
                "close_time": START_15M + (index + 1) * 900_000 - 1,
            }
            for index in range(rows)
        ]
    )


def _klines_1h(rows: int = 80) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "open_time": START_1H + index * 3_600_000,
                "open": 100 + index * 0.1 - 0.1,
                "high": 100 + index * 0.1 + 0.5,
                "low": 100 + index * 0.1 - 0.5,
                "close": 100 + index * 0.1,
                "volume": 100.0,
                "close_time": START_1H + (index + 1) * 3_600_000 - 1,
            }
            for index in range(rows)
        ]
    )


def _force_rsi(monkeypatch, value: float) -> None:
    monkeypatch.setattr(
        "src.production_parity_15m.compute_rsi",
        lambda close: pd.Series([value] * len(close), index=close.index),
    )


@pytest.mark.parametrize(
    ("rows_15m", "rows_1h", "reason"),
    [
        (59, 80, "insufficient_15m_data"),
        (80, 59, "insufficient_1h_data"),
    ],
)
def test_insufficient_15m_or_1h_data_has_no_candidate(rows_15m, rows_1h, reason):
    result = evaluate_15m_long_candidate(
        _klines_15m(rows_15m),
        _klines_1h(rows_1h),
        symbol="BTCUSDT",
    )

    assert result == ParityEvaluation(None, reason)


@pytest.mark.parametrize(
    ("candle_range", "reason"),
    [
        (0.4, "atr_below_production_range"),
        (4.0, "atr_above_production_range"),
    ],
)
def test_atr_outside_production_range_has_no_candidate(candle_range, reason):
    result = evaluate_15m_long_candidate(
        _klines_15m(candle_range=candle_range),
        _klines_1h(),
        symbol="BTCUSDT",
    )

    assert result.candidate is None
    assert result.pre_candidate_rejection_reason == reason


def test_low_atr_requires_volume_or_structural_confirmation():
    rejected = evaluate_15m_long_candidate(
        _klines_15m(candle_range=0.55, last_volume=10),
        _klines_1h(),
        symbol="BTCUSDT",
    )
    confirmed = evaluate_15m_long_candidate(
        _klines_15m(candle_range=0.55, last_volume=200),
        _klines_1h(),
        symbol="BTCUSDT",
    )

    assert rejected.pre_candidate_rejection_reason == "low_atr_without_confirmation"
    assert confirmed.candidate is not None


def test_supertrend_down_has_no_candidate(monkeypatch):
    monkeypatch.setattr(
        "src.production_parity_15m.compute_supertrend",
        lambda frame: (pd.Series([0.0] * len(frame), index=frame.index), "DOWN"),
    )

    result = evaluate_15m_long_candidate(_klines_15m(), _klines_1h(), symbol="BTCUSDT")

    assert result.candidate is None
    assert result.pre_candidate_rejection_reason == "supertrend_not_up"


def test_supertrend_up_creates_raw_candidate_with_production_prices():
    signal = production_like_raw_signal_from_klines(
        "btcusdt",
        "15m",
        _klines_15m(),
        _klines_1h(),
    )

    assert signal is not None
    assert signal.symbol == "BTCUSDT"
    assert signal.direction == "LONG"
    assert signal.entry == 100.0
    assert signal.sl == 98.5
    assert signal.tp == 102.25
    assert signal.rr_ratio == 1.5
    assert signal.risk_distance == 1.5
    assert signal.reward_distance == 2.25
    assert signal.actual_rr == 1.5
    assert signal.production_signal_id == f"BTCUSDT:15m:{START_15M + 79 * 900_000}:LONG"
    assert signal.signal_id == signal.production_signal_id


@pytest.mark.parametrize(
    ("rsi", "would_allow", "reason"),
    [
        (34.99, False, "rsi_below_35"),
        (35.0, True, None),
        (65.0, True, None),
        (65.01, False, "rsi_above_65"),
    ],
)
def test_post_candidate_rsi_gates_preserve_candidate(monkeypatch, rsi, would_allow, reason):
    _force_rsi(monkeypatch, rsi)

    signal = production_like_raw_signal_from_klines(
        "BTCUSDT",
        "15m",
        _klines_15m(),
        _klines_1h(),
    )

    assert signal is not None
    assert signal.production_would_allow is would_allow
    assert (reason in signal.production_block_reasons) if reason else signal.production_block_reasons == []


def test_bearish_pattern_blocks_after_raw_boundary(monkeypatch):
    monkeypatch.setattr(
        "src.production_parity_15m.detect_pattern",
        lambda *_args, **_kwargs: "Bearish Engulfing",
    )

    signal = production_like_raw_signal_from_klines(
        "BTCUSDT",
        "15m",
        _klines_15m(),
        _klines_1h(),
    )

    assert signal is not None
    assert signal.pattern == "Bearish Engulfing"
    assert signal.production_would_allow is False
    assert "bearish_pattern_against_long" in signal.production_block_reasons


def test_sl_too_wide_blocks_after_boundary():
    signal = production_like_raw_signal_from_klines(
        "BTCUSDT",
        "15m",
        _klines_15m(candle_range=3.0),
        _klines_1h(),
    )

    assert signal is not None
    assert signal.sl_pct > 0.035
    assert "sl_too_wide_15m" in signal.production_block_reasons


def test_rounding_can_produce_sl_too_tight_after_boundary():
    price = 1001.49
    signal = production_like_raw_signal_from_klines(
        "BTCUSDT",
        "15m",
        _klines_15m(price=price, candle_range=price * 0.005001),
        _klines_1h(),
    )

    assert signal is not None
    assert signal.sl_pct < 0.0075
    assert "sl_too_tight_15m" in signal.production_block_reasons


def test_market_mode_no_trade_and_score_are_analytics_only():
    signal = production_like_raw_signal_from_klines(
        "BTCUSDT",
        "15m",
        _klines_15m(),
        _klines_1h(),
    )

    assert signal is not None
    assert signal.market_mode_pre.startswith("NO_TRADE")
    assert signal.market_mode_post == signal.market_mode_pre
    assert signal.score is not None
    assert signal.production_would_allow is True
    assert "market_mode_15m_no_trade" not in signal.production_block_reasons


def test_htf_uses_only_closed_1h_candles_available_at_candidate_time():
    baseline = _klines_1h()
    target_close = int(_klines_15m().iloc[-1]["close_time"])
    future = baseline.iloc[-1].copy()
    future["open_time"] = target_close - 1_000
    future["close_time"] = target_close + 3_599_000
    future["open"] = 1.0
    future["high"] = 2.0
    future["low"] = 0.5
    future["close"] = 0.5
    with_future = pd.concat([baseline, pd.DataFrame([future])], ignore_index=True)

    original = production_like_raw_signal_from_klines(
        "BTCUSDT", "15m", _klines_15m(), baseline
    )
    guarded = production_like_raw_signal_from_klines(
        "BTCUSDT", "15m", _klines_15m(), with_future
    )

    assert original is not None and guarded is not None
    assert original.trend_htf == "Long"
    assert guarded.trend_htf == original.trend_htf


def test_rsi_formula_matches_production_zero_loss_behavior():
    close = pd.Series(range(1, 81), dtype=float)

    assert compute_rsi(close).iloc[-1] == 50.0


def test_missing_htf_and_unsupported_timeframe_emit_no_candidate():
    assert production_like_raw_signal_from_klines("BTCUSDT", "15m", _klines_15m()) is None
    assert production_like_raw_signal_from_klines(
        "BTCUSDT", "5m", _klines_15m(), _klines_1h()
    ) is None


def test_fixture_sequence_is_not_automatically_candidate_per_candle(monkeypatch):
    frames = [
        _klines_15m(candle_range=0.4),
        _klines_15m(),
        _klines_15m(),
    ]
    original_supertrend = __import__(
        "src.production_parity_15m", fromlist=["compute_supertrend"]
    ).compute_supertrend
    calls = {"count": 0}

    def supertrend(frame):
        calls["count"] += 1
        if calls["count"] == 2:
            return original_supertrend(frame)
        return pd.Series([0.0] * len(frame), index=frame.index), "DOWN"

    monkeypatch.setattr("src.production_parity_15m.compute_supertrend", supertrend)
    results = [
        production_like_raw_signal_from_klines("BTCUSDT", "15m", frame, _klines_1h())
        for frame in frames
    ]

    assert sum(signal is not None for signal in results) == 1


def test_allowed_and_blocked_candidates_reach_hypothesis_fanout(monkeypatch, tmp_path):
    allowed = production_like_raw_signal_from_klines(
        "BTCUSDT", "15m", _klines_15m(), _klines_1h()
    )
    _force_rsi(monkeypatch, 32.0)
    blocked = production_like_raw_signal_from_klines(
        "ETHUSDT", "15m", _klines_15m(), _klines_1h()
    )

    assert allowed is not None and allowed.production_would_allow is True
    assert blocked is not None and blocked.production_would_allow is False
    runner = HypothesisRunner(data_root=tmp_path)
    runner.process_signal(allowed)
    runner.process_signal(blocked)

    assert len(runner.events) == 30
    assert len(runner.portfolios["baseline_rr15"].open_positions) == 2
    blocked_events = [event for event in runner.events if event["symbol"] == "ETHUSDT"]
    assert blocked_events
    assert all(event["production_would_allow"] is False for event in blocked_events)
    assert all(event["production_signal_id"] == blocked.production_signal_id for event in blocked_events)
    assert all(event["entry"] == blocked.entry for event in blocked_events)
    assert all(event["sl"] == blocked.sl for event in blocked_events)
    assert all(event["tp"] == blocked.tp for event in blocked_events)
