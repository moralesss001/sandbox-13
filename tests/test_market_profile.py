from copy import deepcopy

import pandas as pd
import pytest

import src.production_like_raw_source as raw_source
from src.production_parity_15m import ParityEvaluation

from src.market_profile import attach_market_profile, classify_market_profile, rsi_zone
from src.order_models import SignalCandidate, ensure_candidate_id


@pytest.mark.parametrize(
    ("value", "expected"),
    [(34.99, "<35"), (35.0, "35-40"), (39.99, "35-40"), (40.0, "40-65"), (65.0, "40-65"), (65.01, ">65"), (None, "UNKNOWN"), (float("nan"), "UNKNOWN"), (float("inf"), "UNKNOWN")],
)
def test_rsi_zone_boundaries(value, expected):
    assert rsi_zone(value) == expected


@pytest.mark.parametrize(
    ("setup", "phase", "expected"),
    [("rebound", "range", "REBOUND"), ("continuation", "trend", "CONTINUATION"), ("unknown", "trend", "DEFENSIVE"), ("breakout", "range", "DEFENSIVE"), ("breakout", "trend", "UNKNOWN")],
)
def test_market_profile_primary_rules(setup, phase, expected):
    result = classify_market_profile(
        setup_type=setup,
        rsi=50,
        market_phase=phase,
        session="US",
        trend_htf="Long",
        macd=True,
        volume=True,
    )
    assert result.market_profile_v1 == expected


@pytest.mark.parametrize(
    ("rsi", "htf", "macd", "expected"),
    [(50, "Long", True, "LOW"), (39, "Long", True, "MEDIUM"), (39, "Short", True, "HIGH"), (50, "Short", False, "HIGH")],
)
def test_rebound_confidence_is_transparent(rsi, htf, macd, expected):
    result = classify_market_profile(
        setup_type="rebound",
        rsi=rsi,
        market_phase="unclear",
        session="EUROPE",
        trend_htf=htf,
        macd=macd,
        volume=False,
    )
    assert result.market_profile_confidence == expected



def test_boolean_analytics_are_provider_independent():
    numeric = classify_market_profile(
        setup_type="rebound", rsi=50, market_phase="unclear", session="US",
        trend_htf="Short", macd=0, volume=1,
    )
    text = classify_market_profile(
        setup_type="continuation", rsi=50, market_phase="trend", session="US",
        trend_htf="Long", macd="true", volume="1",
    )
    assert numeric.profile_macd_false is True
    assert numeric.market_profile_confidence == "HIGH"
    assert text.market_profile_confidence == "HIGH"


def test_continuation_and_defensive_confidence():
    continuation = classify_market_profile(
        setup_type="continuation", rsi=50, market_phase="trend", session="US", trend_htf="Long", macd=True, volume=False
    )
    defensive = classify_market_profile(
        setup_type="unknown", rsi=50, market_phase="range", session="ASIA", trend_htf="Short", macd=False, volume=False
    )
    assert continuation.market_profile_confidence == "HIGH"
    assert defensive.market_profile_confidence == "HIGH"


def test_profile_attachment_does_not_change_candidate_contract():
    signal = SignalCandidate(
        symbol="BTCUSDT", timeframe="15m", direction="LONG", entry=100, sl=98, tp=103,
        rr_ratio=1.5, created_at="2026-08-13T00:00:00+00:00", setup_type="rebound",
        rsi=39, market_phase="range", session="US", trend_htf="Short", macd=False,
        volume=True, candidate_source="production_like_raw", candidate_source_version="v2",
        production_would_allow=False, production_block_reasons=["rsi_below_35"],
        raw={"close_time": 123},
    )
    candidate_id = ensure_candidate_id(signal)
    protected = deepcopy({key: getattr(signal, key) for key in (
        "candidate_id", "signal_id", "production_would_allow", "production_block_reasons",
        "entry", "sl", "tp", "rr_ratio", "direction",
    )})

    attach_market_profile(signal)

    assert ensure_candidate_id(signal) == candidate_id
    assert {key: getattr(signal, key) for key in protected} == protected
    assert signal.market_profile_v1 == "REBOUND"
    assert signal.raw["market_profile_version"] == "v1"



def test_market_profile_does_not_change_raw_candidate_count(monkeypatch):
    parity = {
        "symbol": "BTCUSDT", "timeframe": "15m", "direction": "LONG",
        "entry": 100.0, "sl": 98.5, "tp": 102.25, "rr_ratio": 1.5,
        "signal_id": "BTCUSDT:15m:1:LONG", "production_signal_id": "BTCUSDT:15m:1:LONG",
        "source_candle_close_time_ms": 1_700_000_000_000, "rsi": 39.0, "atr": 1.0,
        "atr_pct": 0.01, "sl_pct": 0.015, "risk_distance": 1.5,
        "reward_distance": 2.25, "actual_rr": 1.5, "score": 80, "pattern": None,
        "supertrend_dir": "UP", "macd": False, "volume": True, "candle_body": True,
        "market_mode_pre": "NO_TRADE", "market_mode_post": "NO_TRADE",
        "market_phase": "range", "session_msk_raw": "US", "setup_type": "rebound",
        "trend_htf": "Short", "reason": "trend", "confidence_factors": {},
    }
    frame = pd.DataFrame([{"close_time": 1_700_000_000_000, "close": 100.0}])
    monkeypatch.setattr(raw_source, "evaluate_15m_long_candidate", lambda *_a, **_k: ParityEvaluation(parity, None))
    original_attach = raw_source.attach_market_profile
    monkeypatch.setattr(raw_source, "attach_market_profile", lambda signal: signal)
    before = [raw_source.production_like_raw_signal_from_klines("BTCUSDT", "15m", frame, frame)]
    monkeypatch.setattr(raw_source, "attach_market_profile", original_attach)
    after = [raw_source.production_like_raw_signal_from_klines("BTCUSDT", "15m", frame, frame)]
    assert sum(item is not None for item in before) == sum(item is not None for item in after) == 1

    monkeypatch.setattr(raw_source, "evaluate_15m_long_candidate", lambda *_a, **_k: ParityEvaluation(None, "pre_boundary"))
    assert raw_source.production_like_raw_signal_from_klines("BTCUSDT", "15m", frame, frame) is None


def test_profile_attachment_does_not_change_independently_computed_candidate_id():
    values = dict(
        symbol="BTCUSDT", timeframe="15m", direction="LONG", entry=100, sl=98, tp=103,
        rr_ratio=1.5, created_at="2026-08-13T00:00:00+00:00", setup_type="rebound",
        rsi=39, market_phase="range", session="US", trend_htf="Short", macd=False,
        volume=True, candidate_source="production_like_raw", candidate_source_version="v2",
        raw={"close_time": 123},
    )
    plain = SignalCandidate(**values)
    profiled = SignalCandidate(**values)
    attach_market_profile(profiled)
    assert ensure_candidate_id(plain) == ensure_candidate_id(profiled)
