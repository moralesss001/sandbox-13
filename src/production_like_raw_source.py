from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .candidate_sources import PRODUCTION_LIKE_RAW_METADATA
from .order_models import SignalCandidate
from .session_classifier import normalize_session
from .shadow_gates import attach_shadow_gate_metadata


def _to_numeric_frame(klines: pd.DataFrame) -> pd.DataFrame:
    work = klines.copy()
    for column in ["open", "high", "low", "close", "volume"]:
        if column not in work.columns:
            work[column] = 0.0
        work[column] = pd.to_numeric(work[column], errors="coerce")
    return work.dropna(subset=["open", "high", "low", "close"])


def _rsi(closes: pd.Series, period: int = 14) -> float:
    delta = closes.astype(float).diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    last_loss = loss.iloc[-1] if len(loss) else 0.0
    last_gain = gain.iloc[-1] if len(gain) else 0.0
    if pd.isna(last_gain) or pd.isna(last_loss):
        return 50.0
    if float(last_loss) == 0.0:
        return 100.0 if float(last_gain) > 0 else 50.0
    rs = float(last_gain) / float(last_loss)
    return float(100 - (100 / (1 + rs)))


def _atr(work: pd.DataFrame, period: int = 14) -> float:
    high = work["high"].astype(float)
    low = work["low"].astype(float)
    close = work["close"].astype(float)
    prev_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    value = true_range.rolling(period).mean().iloc[-1]
    if pd.isna(value) or value <= 0:
        return 0.0
    return float(value)


def _session_from_timestamp(row: pd.Series) -> str:
    raw = row.get("close_time", row.get("open_time"))
    try:
        timestamp = pd.to_datetime(float(raw), unit="ms", utc=True)
    except (TypeError, ValueError, OverflowError):
        timestamp = pd.Timestamp.now(tz="UTC")
    hour_msk = int(timestamp.tz_convert("Europe/Moscow").hour)
    if 0 <= hour_msk < 8:
        return "ASIA"
    if 8 <= hour_msk < 14:
        return "EUROPE"
    if 14 <= hour_msk < 17:
        return "OVERLAP"
    if 17 <= hour_msk <= 23:
        return "US"
    return "UNKNOWN"


def _ema_slope_pct(closes: pd.Series, span: int = 20) -> float:
    ema = closes.ewm(span=span, adjust=False).mean()
    if len(ema) < 6 or float(closes.iloc[-1]) == 0.0:
        return 0.0
    return float((ema.iloc[-1] - ema.iloc[-6]) / closes.iloc[-1])


def _distance_to_ema_pct(closes: pd.Series, span: int = 20) -> float:
    ema = closes.ewm(span=span, adjust=False).mean().iloc[-1]
    last = float(closes.iloc[-1])
    if last == 0.0:
        return 0.0
    return float(abs(last - ema) / last)


def _candle_body_strong(last: pd.Series) -> bool:
    high = float(last["high"])
    low = float(last["low"])
    candle_range = high - low
    if candle_range <= 0:
        return False
    body = abs(float(last["close"]) - float(last["open"]))
    return body / candle_range >= 0.55


def _volume_ok(work: pd.DataFrame) -> bool:
    if "volume" not in work or len(work) < 21:
        return False
    current = float(work["volume"].iloc[-1])
    baseline = float(work["volume"].tail(21).head(20).mean())
    return baseline > 0 and current >= baseline * 0.8


def _impulse_before_entry(closes: pd.Series, atr_value: float) -> bool:
    if len(closes) < 5:
        return False
    move = float(closes.iloc[-1] - closes.iloc[-4])
    return atr_value > 0 and move >= atr_value * 0.8


def _setup_type(rsi_value: float, distance_to_ema: float, impulse: bool, candle_strong: bool) -> str:
    if candle_strong and impulse:
        return "continuation"
    if rsi_value <= 45 and distance_to_ema <= 0.003:
        return "rebound"
    return "unknown"


def _market_phase(atr_pct: float, slope_pct: float, distance_to_ema: float, impulse: bool) -> str:
    if impulse and abs(slope_pct) >= 0.002:
        return "trend"
    if atr_pct < 0.0045 and abs(slope_pct) < 0.0015 and distance_to_ema < 0.004:
        return "range"
    return "unclear"


def _market_mode(rsi_value: float, volume_ok: bool, candle_strong: bool, impulse: bool) -> str:
    if rsi_value <= 32 and volume_ok and candle_strong:
        return "EXTREME_REVERSION:extreme_reversion_long"
    if impulse and candle_strong and volume_ok:
        return "IMPULSE_CONTINUATION:pullback_impulse"
    return "NO_TRADE:flat_no_impulse_no_extreme"


def _score_analytics(
    rsi_value: float,
    atr_pct: float,
    macd_ok: bool,
    volume_ok: bool,
    candle_strong: bool,
    htf_aligned: bool,
) -> int:
    score = 35
    if 35 <= rsi_value <= 65:
        score += 20
    elif rsi_value <= 30:
        score -= 10
    if 0.0045 <= atr_pct <= 0.012:
        score += 10
    if macd_ok:
        score += 10
    if volume_ok:
        score += 10
    if candle_strong:
        score += 10
    if htf_aligned:
        score += 5
    return max(0, min(100, int(score)))


def production_like_raw_signal_from_klines(
    symbol: str,
    timeframe: str,
    klines: pd.DataFrame,
) -> SignalCandidate | None:
    if timeframe != "15m":
        return None
    work = _to_numeric_frame(klines)
    if len(work) < 30:
        return None

    last = work.iloc[-1]
    closes = work["close"].astype(float)
    entry = float(last["close"])
    if entry <= 0:
        return None

    atr_value = _atr(work)
    risk_distance = max(atr_value, entry * 0.003)
    rsi_value = _rsi(closes)
    atr_pct = atr_value / entry if entry else 0.0
    ema_fast = closes.ewm(span=12, adjust=False).mean().iloc[-1]
    ema_slow = closes.ewm(span=26, adjust=False).mean().iloc[-1]
    macd_ok = bool(ema_fast >= ema_slow)
    volume_confirmed = _volume_ok(work)
    candle_strong = _candle_body_strong(last)
    slope_pct = _ema_slope_pct(closes)
    distance_to_ema = _distance_to_ema_pct(closes)
    impulse = _impulse_before_entry(closes, atr_value)
    trend_htf = "Long" if entry >= float(closes.tail(50).mean()) else "Short"
    htf_aligned = trend_htf == "Long"
    setup = _setup_type(rsi_value, distance_to_ema, impulse, candle_strong)
    phase = _market_phase(atr_pct, slope_pct, distance_to_ema, impulse)
    mode = _market_mode(rsi_value, volume_confirmed, candle_strong, impulse)
    session = normalize_session(_session_from_timestamp(last))
    score = _score_analytics(rsi_value, atr_pct, macd_ok, volume_confirmed, candle_strong, htf_aligned)

    raw = last.to_dict()
    raw.update(
        {
            "market_mode_15m": mode,
            "market_mode": mode,
            "score": score,
            "score_label": "LOW_SCORE" if score < 50 else "OK_SCORE",
            "score_analytics_only": True,
            "score_used_as_gate": False,
            "rsi_gate_analytics_only": True,
            "market_mode_gate_analytics_only": True,
            "macd_ok": macd_ok,
            "volume_ok": volume_confirmed,
            "candle_strong": candle_strong,
            "ema_slope_pct": slope_pct,
            "distance_to_ema_pct": distance_to_ema,
            "impulse_before_entry": impulse,
            "atr": atr_value,
            "atr_pct": atr_pct,
            "session_msk": session,
        }
    )

    candidate = SignalCandidate(
        symbol=symbol.upper(),
        timeframe=timeframe,
        direction="LONG",
        entry=entry,
        tp=entry + risk_distance * 1.5,
        sl=entry - risk_distance,
        rr_ratio=1.5,
        created_at=datetime.now(timezone.utc).isoformat(),
        rsi=rsi_value,
        atr_pct=atr_pct,
        market_phase=phase,
        session=session,
        setup_type=setup,
        trend_htf=trend_htf,
        reason="production_like_raw_long",
        confidence_factors={
            "score": score,
            "score_analytics_only": True,
            "macd_ok": macd_ok,
            "volume_ok": volume_confirmed,
            "candle_strong": candle_strong,
            "htf_aligned": htf_aligned,
        },
        signal_source="production_like_raw_live",
        source="binance_public_rest",
        **PRODUCTION_LIKE_RAW_METADATA.as_candidate_kwargs(),
        raw=raw,
    )
    return attach_shadow_gate_metadata(candidate)
