from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd


RSI_PERIOD = 14
ATR_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
VOL_WINDOW = 20
VOL_MULT = 0.95
ST_MULTIPLIER = 2.7
LITE_15M_MIN_ATR_PCT = 0.0050
LITE_15M_MAX_ATR_PCT = 0.0350
LITE_MIN_ATR_PCT = 0.0060
LITE_SL_MULT = 1.5
MIN_RSI_15M_LONG = 35.0
MAX_RSI_15M_LONG = 65.0
MIN_SL_PCT_15M = 0.0075
MAX_SL_PCT_15M = 0.035
RISK_REWARD_RATIO_15M = 1.5

STRUCT_PATTERNS = (
    "Bullish Engulfing",
    "Bearish Engulfing",
    "Hammer",
    "Shooting Star",
    "Bullish Pinbar",
    "Bearish Pinbar",
    "Evening Star",
    "Break+Retest Up",
    "Break+Retest Down",
)
BEARISH_PATTERNS = (
    "Bearish Engulfing",
    "Shooting Star",
    "Bearish Pinbar",
    "Evening Star",
    "Break+Retest Down",
)
MIN_PATTERN_VOLUME_MULT = 0.8
MSK = timezone(timedelta(hours=3))


@dataclass(frozen=True)
class ParityEvaluation:
    candidate: dict[str, Any] | None
    pre_candidate_rejection_reason: str | None = None


def prepare_numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError("Missing required OHLCV columns")
    work = frame.copy()
    for column in required:
        work[column] = pd.to_numeric(work[column], errors="raise")
    if work[list(required)].isnull().any().any():
        raise ValueError("NaN in OHLCV data")
    sort_column = "open_time" if "open_time" in work.columns else "time" if "time" in work.columns else None
    if sort_column:
        work[sort_column] = pd.to_numeric(work[sort_column], errors="raise").astype("int64")
        work = work.sort_values(sort_column, kind="stable")
    if "close_time" in work.columns:
        work["close_time"] = pd.to_numeric(work["close_time"], errors="raise").astype("int64")
    return work.reset_index(drop=True)


def compute_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    gain_s = pd.Series(gain, index=close.index)
    loss_s = pd.Series(loss, index=close.index)
    roll_up = gain_s.rolling(period).mean()
    roll_down = loss_s.rolling(period).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = ATR_PERIOD) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def compute_supertrend(frame: pd.DataFrame) -> tuple[pd.Series, str]:
    high = frame["high"].values
    low = frame["low"].values
    close = frame["close"].values
    atr = compute_atr(frame["high"], frame["low"], frame["close"], ATR_PERIOD).values
    hl2 = (high + low) / 2.0
    upperband = hl2 + ST_MULTIPLIER * atr
    lowerband = hl2 - ST_MULTIPLIER * atr
    final_upper = upperband.copy()
    final_lower = lowerband.copy()
    for index in range(1, len(frame)):
        if close[index - 1] > final_upper[index - 1]:
            final_upper[index] = min(upperband[index], final_upper[index - 1])
        else:
            final_upper[index] = upperband[index]
        if close[index - 1] < final_lower[index - 1]:
            final_lower[index] = max(lowerband[index], final_lower[index - 1])
        else:
            final_lower[index] = lowerband[index]
    supertrend = np.empty(len(frame))
    supertrend[0] = final_lower[0] if close[0] >= final_lower[0] else final_upper[0]
    for index in range(1, len(frame)):
        if supertrend[index - 1] == final_upper[index - 1]:
            supertrend[index] = final_upper[index] if close[index] <= final_upper[index] else final_lower[index]
        else:
            supertrend[index] = final_lower[index] if close[index] >= final_lower[index] else final_upper[index]
    direction = "UP" if close[-1] >= supertrend[-1] else "DOWN"
    return pd.Series(supertrend, index=frame.index), direction


def _safe_candle_values(frame: pd.DataFrame, index: int = -1) -> tuple[float, float, float, float]:
    row = frame.iloc[index]
    values = tuple(float(row[column]) for column in ("open", "close", "high", "low"))
    if any(pd.isna(value) for value in values):
        raise ValueError("NaN in candle")
    return values


def candle_body_strong(frame: pd.DataFrame, index: int = -1) -> bool:
    try:
        open_price, close_price, high, low = _safe_candle_values(frame, index)
        candle_range = high - low
        return candle_range > 0 and abs(close_price - open_price) / candle_range > 0.6
    except (ValueError, IndexError):
        return False


def _pinbar_type(open_price: float, close_price: float, high: float, low: float) -> str | None:
    candle_range = max(1e-12, high - low)
    body = abs(close_price - open_price)
    upper = high - max(open_price, close_price)
    lower = min(open_price, close_price) - low
    if body / candle_range > 0.30:
        return None
    if lower / candle_range >= 0.60 and upper / candle_range <= 0.20:
        return "Bullish Pinbar"
    if upper / candle_range >= 0.60 and lower / candle_range <= 0.20:
        return "Bearish Pinbar"
    return None


def _morning_evening_star(frame: pd.DataFrame) -> str | None:
    if len(frame) < 5:
        return None
    try:
        first, middle, last = frame.iloc[-3], frame.iloc[-2], frame.iloc[-1]
        o1, c1, h1, l1 = (float(first[key]) for key in ("open", "close", "high", "low"))
        o2, c2, h2, l2 = (float(middle[key]) for key in ("open", "close", "high", "low"))
        o3, c3, h3, l3 = (float(last[key]) for key in ("open", "close", "high", "low"))
        body1 = abs(c1 - o1) / max(1e-12, h1 - l1)
        body2 = abs(c2 - o2) / max(1e-12, h2 - l2)
        body3 = abs(c3 - o3) / max(1e-12, h3 - l3)
        if body2 > 0.25:
            return None
        if c1 > o1 and c3 < o3 and body1 > 0.45 and body3 > 0.45 and c3 <= (o1 + c1) / 2.0:
            return "Evening Star"
    except (ValueError, IndexError):
        return None
    return None


def _break_retest(frame: pd.DataFrame) -> str | None:
    if len(frame) < 30:
        return None
    window = frame.tail(25).copy()
    base_period = window.iloc[:20]
    level_high = float(base_period["high"].max())
    level_low = float(base_period["low"].min())
    tail = window.iloc[20:]
    last = window.iloc[-1]
    last_close = float(last["close"])
    last_open = float(last["open"])
    last_high = float(last["high"])
    last_low = float(last["low"])
    if (tail["close"] > level_high).any():
        retest = (tail["low"] <= level_high) & (tail["close"] >= level_high)
        if retest.any() and last_close > last_open and last_low <= level_high and last_close >= level_high:
            return "Break+Retest Up"
    if (tail["close"] < level_low).any():
        retest = (tail["high"] >= level_low) & (tail["close"] <= level_low)
        if retest.any() and last_close < last_open and last_high >= level_low and last_close <= level_low:
            return "Break+Retest Down"
    return None


def detect_pattern(frame: pd.DataFrame, volume_mean: float, current_volume: float) -> str | None:
    if len(frame) < 5:
        return None
    has_min_volume = volume_mean > 0 and current_volume >= volume_mean * MIN_PATTERN_VOLUME_MULT
    try:
        previous, current = frame.iloc[-2], frame.iloc[-1]
        o1, c1 = float(previous["open"]), float(previous["close"])
        o2, c2 = float(current["open"]), float(current["close"])
        if c1 < o1 and c2 > o2 and c2 >= o1 and o2 <= c1:
            return "Bullish Engulfing" if has_min_volume else None
        if c1 > o1 and c2 < o2 and c2 <= o1 and o2 >= c1:
            return "Bearish Engulfing" if has_min_volume else None
        star = _morning_evening_star(frame)
        if star:
            return star if has_min_volume else None
        open_price, close_price, high, low = _safe_candle_values(frame, -1)
        candle_range = max(1e-12, high - low)
        body = abs(close_price - open_price)
        upper_wick = high - max(open_price, close_price)
        lower_wick = min(open_price, close_price) - low
        if body / candle_range <= 0.12:
            return "Doji"
        pinbar = _pinbar_type(open_price, close_price, high, low)
        if pinbar:
            return pinbar if has_min_volume else None
        if lower_wick / candle_range >= 0.55 and upper_wick / candle_range <= 0.20 and body / candle_range <= 0.35:
            return "Hammer" if has_min_volume else None
        if upper_wick / candle_range >= 0.55 and lower_wick / candle_range <= 0.20 and body / candle_range <= 0.35:
            return "Shooting Star" if has_min_volume else None
        retest = _break_retest(frame)
        return retest if retest and has_min_volume else None
    except (ValueError, IndexError):
        return None


def has_structure(pattern: str | None) -> bool:
    return bool(pattern) and pattern in STRUCT_PATTERNS and pattern != "Doji"


def pattern_against_long(pattern: str | None) -> bool:
    return bool(pattern) and pattern in BEARISH_PATTERNS


def _pullback_context_long(frame: pd.DataFrame, rsi_value: float) -> bool:
    if len(frame) < 18 or rsi_value > 50.0:
        return False
    last = frame.tail(14).copy()
    bodies = (last["close"] - last["open"]).abs()
    ranges = (last["high"] - last["low"]).replace(0, np.nan)
    body_ratio = (bodies / ranges).fillna(0)
    impulse_window = last.iloc[:9]
    impulse = ((impulse_window["close"] > impulse_window["open"]) & (body_ratio.iloc[:9] > 0.55)).any()
    if not impulse:
        return False
    if int((last.tail(5)["close"] > last.tail(5)["open"]).sum()) >= 4:
        return False
    open_price, close_price, _, _ = _safe_candle_values(frame, -1)
    return close_price > open_price


def detect_market_mode_15m(
    frame: pd.DataFrame,
    rsi_value: float,
    volume_ok: bool,
    pattern: str | None,
    strong_candle: bool,
    supertrend_direction: str,
) -> tuple[str, str]:
    if rsi_value <= 32 and volume_ok and pattern in STRUCT_PATTERNS:
        return "EXTREME_REVERSION", "extreme_reversion_long"
    impulse_confirmed = volume_ok and strong_candle and supertrend_direction == "UP"
    if _pullback_context_long(frame, rsi_value) and impulse_confirmed:
        return "IMPULSE_CONTINUATION", "pullback_impulse"
    return "NO_TRADE", "flat_no_impulse_no_extreme"


def _ema_slope_pct(close: pd.Series, period: int = 20, lookback: int = 3) -> float:
    ema = close.ewm(span=period, adjust=False).mean()
    base = float(ema.iloc[-lookback - 1])
    return 0.0 if base == 0 else (float(ema.iloc[-1]) - base) / base


def _distance_to_ema_pct(close: pd.Series, period: int = 20) -> float:
    ema_last = float(close.ewm(span=period, adjust=False).mean().iloc[-1])
    return 0.0 if ema_last == 0 else (float(close.iloc[-1]) - ema_last) / ema_last


def _impulse_before_entry(frame: pd.DataFrame, volume_ok: bool, strong_candle: bool) -> bool:
    previous = frame.iloc[-4:-1].copy()
    body = (previous["close"] - previous["open"]).abs()
    ranges = (previous["high"] - previous["low"]).replace(0, np.nan)
    body_ratio = (body / ranges).fillna(0)
    bullish_bars = int((previous["close"] > previous["open"]).sum())
    return bool(bullish_bars >= 2 and body_ratio.mean() >= 0.50 and (volume_ok or strong_candle))


def _setup_type(pattern: str | None, rsi_value: float, impulse: bool, distance_to_ema: float) -> str:
    if pattern in ("Break+Retest Up", "Break+Retest Down"):
        return "breakout"
    if rsi_value <= 45 and distance_to_ema <= 0.003:
        return "rebound"
    if impulse:
        return "continuation"
    return "unknown"


def _market_phase(atr_pct: float, slope: float, distance: float, impulse: bool, strong_candle: bool) -> str:
    if impulse and strong_candle and abs(slope) >= 0.0020:
        return "trend"
    if atr_pct < 0.0065 and abs(slope) < 0.0012 and abs(distance) < 0.0040:
        return "range"
    return "unclear"


def _score(
    rsi_value: float,
    macd_ok: bool,
    volume_ok: bool,
    pattern: str | None,
    strong_candle: bool,
    htf_trend: str,
    atr_pct: float,
) -> int:
    score = 55 + int(max(0, 18 - abs(rsi_value - 50.0) * 0.7))
    score += 12 if macd_ok else -8
    score += 10 if volume_ok else -3
    score += 8 if strong_candle else -3
    score += 5 if htf_trend == "Long" else -6
    score += 6
    if pattern_against_long(pattern):
        score -= 25
    elif pattern == "Doji":
        score -= 6
    elif pattern in STRUCT_PATTERNS:
        score += 6
    if LITE_15M_MIN_ATR_PCT <= atr_pct <= 0.020:
        score += 6
    elif atr_pct >= LITE_15M_MIN_ATR_PCT:
        score += 2
    else:
        score -= 10
    score = max(0, min(int(round(score)), 100))
    if score >= 95:
        confirmations = int(volume_ok) + int(macd_ok) + int(bool(pattern and pattern != "Doji" and pattern in STRUCT_PATTERNS))
        if confirmations < 2:
            score = 92
    if not volume_ok and score > 94:
        score = 94
    return score


def round_price(price: float) -> float:
    if price >= 1000:
        return round(price, 1)
    if price >= 100:
        return round(price, 2)
    if price >= 1:
        return round(price, 3)
    return round(price, 5)


def _session(hour_msk: int) -> str:
    if 0 <= hour_msk < 8:
        return "ASIA"
    if 8 <= hour_msk < 14:
        return "EU"
    if 14 <= hour_msk < 17:
        return "EU_US"
    return "US"


def _open_time_ms(row: pd.Series) -> int:
    value = row.get("open_time", row.get("time"))
    if value is None:
        raise ValueError("Missing candle open time")
    return int(value)


def _close_time_ms(row: pd.Series, duration_ms: int) -> int:
    value = row.get("close_time")
    return int(value) if value is not None else _open_time_ms(row) + duration_ms - 1


def evaluate_15m_long_candidate(
    klines_15m: pd.DataFrame,
    klines_1h: pd.DataFrame,
    *,
    symbol: str,
    vol_mult: float = VOL_MULT,
    rr_ratio: float = RISK_REWARD_RATIO_15M,
) -> ParityEvaluation:
    if rr_ratio <= 0:
        raise ValueError("rr_ratio must be positive")
    try:
        frame_15m = prepare_numeric_frame(klines_15m)
        if len(frame_15m) < 60:
            return ParityEvaluation(None, "insufficient_15m_data")
        target = frame_15m.iloc[-1]
        target_close_time = _close_time_ms(target, 900_000)
        frame_1h = prepare_numeric_frame(klines_1h)
        if "close_time" in frame_1h.columns:
            frame_1h = frame_1h[frame_1h["close_time"] <= target_close_time].copy()
        else:
            frame_1h = frame_1h[
                frame_1h.apply(lambda row: _open_time_ms(row) + 3_600_000 - 1 <= target_close_time, axis=1)
            ].copy()
        if len(frame_1h) < 60:
            return ParityEvaluation(None, "insufficient_1h_data")

        close = frame_15m["close"]
        volume = frame_15m["volume"]
        price = float(close.iloc[-1])
        rsi_value = float(round(compute_rsi(close).iloc[-1], 2))
        atr_value = float(compute_atr(frame_15m["high"], frame_15m["low"], close).iloc[-1])
        atr_pct = atr_value / price if price > 0 else 0.0
        ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
        ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
        macd_ok = bool(ema_fast.iloc[-1] > ema_slow.iloc[-1])
        volume_mean = volume.rolling(VOL_WINDOW).mean()
        volume_ok = bool(volume_mean.iloc[-1] > 0 and volume.iloc[-1] > volume_mean.iloc[-1] * vol_mult)
        strong_candle = candle_body_strong(frame_15m)
        _, supertrend_direction = compute_supertrend(frame_15m)
        htf_close = frame_1h["close"]
        htf_mean = htf_close.rolling(50).mean().fillna(htf_close.mean())
        htf_trend = "Long" if htf_close.iloc[-1] > htf_mean.iloc[-1] else "Short"
        pattern = detect_pattern(frame_15m, float(volume_mean.iloc[-1]), float(volume.iloc[-1]))
    except (KeyError, TypeError, ValueError, OverflowError, IndexError):
        return ParityEvaluation(None, "indicator_calculation_error")

    if atr_pct < LITE_15M_MIN_ATR_PCT:
        return ParityEvaluation(None, "atr_below_production_range")
    if atr_pct > LITE_15M_MAX_ATR_PCT:
        return ParityEvaluation(None, "atr_above_production_range")
    if atr_pct < LITE_MIN_ATR_PCT and not (volume_ok or has_structure(pattern)):
        return ParityEvaluation(None, "low_atr_without_confirmation")
    if supertrend_direction != "UP":
        return ParityEvaluation(None, "supertrend_not_up")

    candle_open_time_ms = _open_time_ms(target)
    production_close_time_ms = candle_open_time_ms + 900_000 - 1
    signal_id = f"{symbol.upper()}:15m:{candle_open_time_ms}:LONG"
    created_at_msk = datetime.fromtimestamp(candle_open_time_ms / 1000, tz=timezone.utc).astimezone(MSK)
    hour_msk = created_at_msk.hour
    mode, mode_reason = detect_market_mode_15m(
        frame_15m,
        rsi_value,
        volume_ok,
        pattern,
        strong_candle,
        supertrend_direction,
    )
    market_mode = f"{mode}:{mode_reason}"
    impulse = _impulse_before_entry(frame_15m, volume_ok, strong_candle)
    slope = _ema_slope_pct(close)
    distance = _distance_to_ema_pct(close)
    setup_type = _setup_type(pattern, rsi_value, impulse, distance)
    market_phase = _market_phase(atr_pct, slope, distance, impulse, strong_candle)
    score = _score(rsi_value, macd_ok, volume_ok, pattern, strong_candle, htf_trend, atr_pct)

    entry = round_price(price)
    sl = round_price(entry - LITE_SL_MULT * atr_value)
    risk_distance = abs(entry - sl)
    tp = round_price(entry + risk_distance * rr_ratio)
    reward_distance = abs(tp - entry)
    actual_rr = reward_distance / risk_distance if risk_distance > 0 else 0.0
    sl_pct = risk_distance / entry if entry > 0 else 0.0
    confirmations_count = int(volume_ok) + int(macd_ok) + int(bool(pattern and pattern != "Doji" and pattern in STRUCT_PATTERNS))
    confidence_factors = {
        "vol_confirmed": volume_ok,
        "pattern_aligned": bool(pattern and not pattern_against_long(pattern)),
        "htf_aligned": htf_trend == "Long",
        "st_aligned": True,
        "rsi_optimal": 40 <= rsi_value <= 60,
        "atr_optimal": LITE_15M_MIN_ATR_PCT <= atr_pct <= 0.020,
        "low_confidence_time": hour_msk in (16, 17),
    }
    return ParityEvaluation(
        {
            "production_signal_id": signal_id,
            "signal_id": signal_id,
            "symbol": symbol.upper(),
            "timeframe": "15m",
            "direction": "LONG",
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "rr_ratio": rr_ratio,
            "actual_rr": actual_rr,
            "risk_distance": risk_distance,
            "reward_distance": reward_distance,
            "sl_pct": sl_pct,
            "rsi": rsi_value,
            "atr": atr_value,
            "atr_pct": atr_pct,
            "macd": macd_ok,
            "volume": volume_ok,
            "pattern": pattern,
            "candle_body": strong_candle,
            "supertrend_dir": supertrend_direction,
            "trend_htf": htf_trend,
            "score": score,
            "score_analytics_only": True,
            "score_used_as_gate": False,
            "market_mode_15m": market_mode,
            "market_mode": market_mode,
            "market_mode_pre": market_mode,
            "market_mode_post": market_mode,
            "market_phase": market_phase,
            "setup_type": setup_type,
            "impulse_before_entry": impulse,
            "session_msk_raw": _session(hour_msk),
            "created_at_msk": created_at_msk.strftime("%Y-%m-%d %H:%M:%S"),
            "hour_msk": hour_msk,
            "low_confidence_time": hour_msk in (16, 17),
            "candle_open_time_ms": candle_open_time_ms,
            "candle_close_time_ms": production_close_time_ms,
            "source_candle_close_time_ms": target_close_time,
            "confirmations_count": confirmations_count,
            "anti_late_blocked": False,
            "reversal_attempted": False,
            "confidence_factors": confidence_factors,
            "reason": "trend",
        }
    )
