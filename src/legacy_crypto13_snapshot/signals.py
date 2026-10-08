# core/signals.py (v2.3.7 - ONLY 1H CHANGED, 15m/4h UNTOUCHED)

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List, Dict, Any
from enum import Enum

import numpy as np
import pandas as pd
import requests

from .config import TP_R_MULT, SL_R_MULT

logger = logging.getLogger(__name__)

API_URL = "https://fapi.binance.com"
API_TIMEOUT = 10
MAX_RETRIES = 3

KLINES_TTL_SECONDS = {
    "15m": 80,
    "1h": 300,
    "4h": 900,
}

_KLINES_CACHE: dict[tuple[str, str, int], tuple[float, pd.DataFrame]] = {}


class SignalRejectionReason(Enum):
    ATR_TOO_LOW = "ATR ниже минимума"
    ATR_TOO_HIGH = "ATR выше максимума"
    NO_STRUCTURE = "Отсутствует структура"
    RSI_HARD_BLOCK = "RSI в зоне жёсткого блока"
    RSI_SAFETY = "RSI не прошёл проверку безопасности"
    PATTERN_AGAINST = "Паттерн против направления"
    DOJI_NO_CONFIRMATION = "Doji без подтверждения"
    NO_VOLUME_WEAK_CANDLE = "Нет объёма и слабая свеча"
    LOW_SCORE = "Score ниже минимального"
    SL_TOO_TIGHT = "SL слишком узкий"
    IMPULSE_AGAINST_HTF = "Импульс против HTF тренда"
    LATE_IMPULSE = "Поздний импульс без структуры"
    INSUFFICIENT_DATA = "Недостаточно данных"
    API_ERROR = "Ошибка API"
    LATE_CANDLE = "Свеча уже слишком поздняя (progress)"
    CHASE_BLOCK = "Слишком сильная погоня (chase ATR)"
    CONFIRMATIONS_LT_2 = "Меньше 2 подтверждений"
    MARKET_MODE_NO_TRADE = "Market mode: NO_TRADE"
    ANTI_LATE_LONG = "Anti-late LONG: RSI высоко и нет структуры"
    SL_TOO_WIDE = "SL слишком широкий (absolute max)"

    ST_NOT_ALIGNED = "SuperTrend не совпадает с направлением"
    MARKET_MODE_15M_NO_TRADE = "15m market mode: NO_TRADE"
    COUNTERTREND_BAN_15M = "15m запрет контртренда (impulse против HTF)"


def _cache_get(symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
    key = (symbol, interval, limit)
    item = _KLINES_CACHE.get(key)
    if not item:
        return None

    ts, df = item
    ttl = KLINES_TTL_SECONDS.get(interval, 60)
    age = datetime.now(timezone.utc).timestamp() - ts
    if age > ttl:
        _KLINES_CACHE.pop(key, None)
        return None
    return df


def _cache_set(symbol: str, interval: str, limit: int, df: pd.DataFrame) -> None:
    key = (symbol, interval, limit)
    _KLINES_CACHE[key] = (datetime.now(timezone.utc).timestamp(), df)


RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
VOL_WINDOW = 20
ATR_PERIOD = 14
ST_MULTIPLIER = 2.7

UTC_PLUS_3 = timezone(timedelta(hours=3))

LITE_MIN_ATR_PCT = 0.006
LITE_MAX_ATR_PCT = 0.12

LITE_15M_MIN_ATR_PCT = 0.0050
LITE_15M_MAX_ATR_PCT = 0.0350

RSI_LONG_MIN = 25.0
RSI_LONG_MAX = 65.0
RSI_SHORT_MIN = 35.0
RSI_SHORT_MAX = 75.0

RSI_15M_LONG_MIN_SOFT = 30.0
RSI_15M_LONG_MAX = 65.0
RSI_15M_SHORT_MIN = 35.0
RSI_15M_SHORT_MAX_SOFT = 70.0

ONE_H_LONG_RSI_ANTI_LATE = 58.0

LITE_SL_MULT = 1.5

ONE_H_SWING_LOOKBACK = 12
ONE_H_STRUCT_BUFFER_ATR = 0.15
ONE_H_MAX_STRUCT_SL_PCT = 0.025
ONE_H_ABSOLUTE_MAX_SL_PCT = 0.035

MIN_SL_PCT_15M = 0.0075

ONE_H_MAX_CANDLE_PROGRESS = 0.75
ONE_H_MAX_CHASE_ATR = 1.20
ONE_H_PENALTY_SCORE = 8

NO_VOL_SCORE_CAP = 94

STRUCT_PATTERNS = (
    "Bullish Engulfing",
    "Bearish Engulfing",
    "Hammer",
    "Shooting Star",
    "Bullish Pinbar",
    "Bearish Pinbar",
    "Morning Star",
    "Evening Star",
    "Break+Retest Up",
    "Break+Retest Down",
)

MIN_PATTERN_VOLUME_MULT = 0.8

BULLISH_PATTERNS = ("Bullish Engulfing", "Hammer", "Bullish Pinbar", "Morning Star", "Break+Retest Up")
BEARISH_PATTERNS = ("Bearish Engulfing", "Shooting Star", "Bearish Pinbar", "Evening Star", "Break+Retest Down")


@dataclass
class Signal:
    symbol: str
    timeframe: str
    direction: str
    entry: float
    tp: float
    sl: float

    score: int
    rsi: float
    macd: bool
    volume: bool
    pattern: Optional[str]
    trend_htf: str
    reason: str
    candle_body: bool

    atr: float
    atr_pct: float
    supertrend_dir: str

    sl_pct: float
    timestamp: str

    signal_id: Optional[str] = None
    candle_open_time_ms: Optional[int] = None
    candle_close_time_ms: Optional[int] = None

    confirmations_count: Optional[int] = None
    market_mode: Optional[str] = None
    market_mode_pre: Optional[str] = None
    market_mode_post: Optional[str] = None
    candle_progress: Optional[float] = None
    chase_atr: Optional[float] = None
    anti_late_blocked: Optional[bool] = None
    reversal_attempted: Optional[bool] = None

    rejection_reasons: Optional[List[str]] = None
    confidence_factors: Optional[dict] = None

    def to_stats_row(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "entry": self.entry,
            "tp": self.tp,
            "sl": self.sl,
            "score": self.score,
            "trend_htf": self.trend_htf,
            "reason": self.reason,
            "pattern": self.pattern,
            "supertrend": self.supertrend_dir,
            "rsi": self.rsi,
            "macd_ok": bool(self.macd),
            "volume_ok": bool(self.volume),
            "candle_strong": bool(self.candle_body),
            "atr_pct": float(self.atr_pct),
            "sl_pct": float(self.sl_pct),
            "candle_open_time_ms": self.candle_open_time_ms,
            "candle_close_time_ms": self.candle_close_time_ms,
            "confirmations_count": self.confirmations_count,
            "market_mode": self.market_mode,
            "market_mode_pre": self.market_mode_pre,
            "market_mode_post": self.market_mode_post,
            "candle_progress": self.candle_progress,
            "chase_atr": self.chase_atr,
            "anti_late_blocked": self.anti_late_blocked,
            "reversal_attempted": self.reversal_attempted,
            "rejection_reasons": "|".join(self.rejection_reasons) if self.rejection_reasons else None,
            "created_at": self.timestamp,
        }


class BinanceAPIError(Exception):
    pass


def _validate_klines_data(data: Any, symbol: str, interval: str) -> None:
    if not isinstance(data, list):
        raise BinanceAPIError(f"Expected list, got {type(data)} for {symbol}/{interval}")
    if len(data) == 0:
        raise BinanceAPIError(f"Empty klines data for {symbol}/{interval}")
    if len(data[0]) < 11:
        raise BinanceAPIError(f"Invalid klines structure for {symbol}/{interval}")


def fetch_klines(symbol: str, interval: str = "1h", limit: int = 200) -> Optional[pd.DataFrame]:
    cached = _cache_get(symbol, interval, limit)
    if cached is not None:
        return cached

    url = f"{API_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=API_TIMEOUT)

            if resp.status_code == 418:
                logger.error(f"Binance 418 for {symbol}/{interval} (temporary ban/edge). Skipping.")
                return None

            if resp.status_code == 429:
                logger.warning(f"Rate limit hit for {symbol}/{interval}, attempt {attempt + 1}")
                if attempt < MAX_RETRIES - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
                raise BinanceAPIError("Rate limit exceeded")

            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict) and "code" in data:
                raise BinanceAPIError(f"Binance API error: {data.get('msg', data)}")

            _validate_klines_data(data, symbol, interval)

            df = pd.DataFrame(
                data,
                columns=[
                    "time", "open", "high", "low", "close", "volume",
                    "ct", "qav", "not", "tbb", "tbq", "ignore"
                ]
            )

            df = df.astype({
                "time": int,
                "open": float,
                "high": float,
                "low": float,
                "close": float,
                "volume": float
            })

            if df[["open", "high", "low", "close"]].isnull().any().any():
                raise BinanceAPIError(f"NaN values in OHLC data for {symbol}/{interval}")

            _cache_set(symbol, interval, limit, df)
            return df

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout fetching {symbol}/{interval}, attempt {attempt + 1}")
            if attempt == MAX_RETRIES - 1:
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {symbol}/{interval}: {e}")
            return None

        except BinanceAPIError as e:
            logger.error(f"Binance API error for {symbol}/{interval}: {e}")
            return None

        except Exception as e:
            logger.error(f"Unexpected error fetching {symbol}/{interval}: {e}", exc_info=True)
            return None

    return None


def compute_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    gain_s = pd.Series(gain, index=close.index)
    loss_s = pd.Series(loss, index=close.index)

    roll_up = gain_s.rolling(period).mean()
    roll_down = loss_s.rolling(period).mean()

    rs = roll_up / roll_down.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = ATR_PERIOD) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def compute_supertrend(df: pd.DataFrame) -> Tuple[pd.Series, str]:
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    atr = compute_atr(df["high"], df["low"], df["close"], ATR_PERIOD).values
    hl2 = (high + low) / 2.0

    upperband = hl2 + ST_MULTIPLIER * atr
    lowerband = hl2 - ST_MULTIPLIER * atr

    final_upper = upperband.copy()
    final_lower = lowerband.copy()

    for i in range(1, len(df)):
        if close[i - 1] > final_upper[i - 1]:
            final_upper[i] = min(upperband[i], final_upper[i - 1])
        else:
            final_upper[i] = upperband[i]

        if close[i - 1] < final_lower[i - 1]:
            final_lower[i] = max(lowerband[i], final_lower[i - 1])
        else:
            final_lower[i] = lowerband[i]

    supertrend = np.empty(len(df))
    supertrend[0] = final_lower[0] if close[0] >= final_lower[0] else final_upper[0]

    for i in range(1, len(df)):
        if supertrend[i - 1] == final_upper[i - 1]:
            supertrend[i] = final_upper[i] if close[i] <= final_upper[i] else final_lower[i]
        else:
            supertrend[i] = final_lower[i] if close[i] >= final_lower[i] else final_upper[i]

    last_dir = "UP" if close[-1] >= supertrend[-1] else "DOWN"
    return pd.Series(supertrend, index=df.index), last_dir


def _safe_candle_values(df: pd.DataFrame, idx: int = -1) -> Tuple[float, float, float, float]:
    o = float(df["open"].iloc[idx])
    c = float(df["close"].iloc[idx])
    h = float(df["high"].iloc[idx])
    l = float(df["low"].iloc[idx])

    if pd.isna(o) or pd.isna(c) or pd.isna(h) or pd.isna(l):
        raise ValueError(f"NaN in OHLC data at index {idx}")
    return o, c, h, l


def _candle_body_strong(df: pd.DataFrame, idx: int = -1) -> bool:
    try:
        o, c, h, l = _safe_candle_values(df, idx)
        rng = h - l
        if rng <= 0:
            return False
        body = abs(c - o)
        return (body / rng) > 0.6
    except (ValueError, IndexError):
        return False


def _pinbar_type(o: float, c: float, h: float, l: float) -> Optional[str]:
    rng = max(1e-12, h - l)
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l

    if (body / rng) > 0.30:
        return None

    if (lower / rng) >= 0.60 and (upper / rng) <= 0.20:
        return "Bullish Pinbar"
    if (upper / rng) >= 0.60 and (lower / rng) <= 0.20:
        return "Bearish Pinbar"
    return None


def _morning_evening_star(df: pd.DataFrame) -> Optional[str]:
    if len(df) < 5:
        return None
    try:
        a = df.iloc[-3]
        b = df.iloc[-2]
        c = df.iloc[-1]

        o1, c1, h1, l1 = float(a["open"]), float(a["close"]), float(a["high"]), float(a["low"])
        o2, c2, h2, l2 = float(b["open"]), float(b["close"]), float(b["high"]), float(b["low"])
        o3, c3, h3, l3 = float(c["open"]), float(c["close"]), float(c["high"]), float(c["low"])

        r1 = max(1e-12, h1 - l1)
        r2 = max(1e-12, h2 - l2)
        r3 = max(1e-12, h3 - l3)

        body1 = abs(c1 - o1) / r1
        body2 = abs(c2 - o2) / r2
        body3 = abs(c3 - o3) / r3

        if body2 > 0.25:
            return None

        if c1 < o1 and c3 > o3 and body1 > 0.45 and body3 > 0.45:
            mid_body_level = (o1 + c1) / 2.0
            if c3 >= mid_body_level:
                return "Morning Star"

        if c1 > o1 and c3 < o3 and body1 > 0.45 and body3 > 0.45:
            mid_body_level = (o1 + c1) / 2.0
            if c3 <= mid_body_level:
                return "Evening Star"

    except (ValueError, IndexError):
        pass

    return None


def _break_retest(df: pd.DataFrame) -> Optional[str]:
    if len(df) < 30:
        return None

    window = df.tail(25).copy()
    base_period = window.iloc[:20]
    lvl_high = float(base_period["high"].max())
    lvl_low = float(base_period["low"].min())

    tail = window.iloc[20:]

    last_candle = window.iloc[-1]
    last_close = float(last_candle["close"])
    last_open = float(last_candle["open"])
    last_high = float(last_candle["high"])
    last_low = float(last_candle["low"])

    broke_up = (tail["close"] > lvl_high).any()
    if broke_up:
        retest_bars = (tail["low"] <= lvl_high) & (tail["close"] >= lvl_high)
        if retest_bars.any():
            if last_close > last_open and last_low <= lvl_high and last_close >= lvl_high:
                return "Break+Retest Up"

    broke_down = (tail["close"] < lvl_low).any()
    if broke_down:
        retest_bars = (tail["high"] >= lvl_low) & (tail["close"] <= lvl_low)
        if retest_bars.any():
            if last_close < last_open and last_high >= lvl_low and last_close <= lvl_low:
                return "Break+Retest Down"

    return None


def detect_pattern(df: pd.DataFrame, vol_ma: float, current_vol: float) -> Optional[str]:
    if len(df) < 5:
        return None

    has_min_volume = (vol_ma > 0 and current_vol >= vol_ma * MIN_PATTERN_VOLUME_MULT)

    try:
        last2 = df.iloc[-2:]
        o1, c1 = float(last2.iloc[0]["open"]), float(last2.iloc[0]["close"])
        o2, c2 = float(last2.iloc[1]["open"]), float(last2.iloc[1]["close"])

        if c1 < o1 and c2 > o2 and c2 >= o1 and o2 <= c1:
            return "Bullish Engulfing" if has_min_volume else None
        if c1 > o1 and c2 < o2 and c2 <= o1 and o2 >= c1:
            return "Bearish Engulfing" if has_min_volume else None

        mes = _morning_evening_star(df)
        if mes:
            return mes if has_min_volume else None

        o, c, h, l = _safe_candle_values(df, -1)

        rng = max(1e-12, h - l)
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l

        if (body / rng) <= 0.12:
            return "Doji"

        pb = _pinbar_type(o, c, h, l)
        if pb:
            return pb if has_min_volume else None

        if (lower_wick / rng) >= 0.55 and (upper_wick / rng) <= 0.20 and (body / rng) <= 0.35:
            return "Hammer" if has_min_volume else None

        if (upper_wick / rng) >= 0.55 and (lower_wick / rng) <= 0.20 and (body / rng) <= 0.35:
            return "Shooting Star" if has_min_volume else None

        br = _break_retest(df)
        if br:
            return br if has_min_volume else None

    except (ValueError, IndexError) as e:
        logger.debug(f"Pattern detection error: {e}")
        return None

    return None


def is_pullback_context_15m(df: pd.DataFrame, direction: str, rsi_val: float) -> bool:
    if len(df) < 18:
        return False

    if direction == "LONG" and rsi_val > 50.0:
        return False
    if direction == "SHORT" and rsi_val < 50.0:
        return False

    last = df.tail(14).copy()
    bodies = (last["close"] - last["open"]).abs()
    ranges = (last["high"] - last["low"]).replace(0, np.nan)
    body_ratio = (bodies / ranges).fillna(0)

    impulse_window = last.iloc[:9]
    if direction == "LONG":
        impulse = ((impulse_window["close"] > impulse_window["open"]) & (body_ratio.iloc[:9] > 0.55)).any()
    else:
        impulse = ((impulse_window["close"] < impulse_window["open"]) & (body_ratio.iloc[:9] > 0.55)).any()

    if not impulse:
        return False

    tail5 = last.tail(5)
    if direction == "LONG":
        trend_streak = int((tail5["close"] > tail5["open"]).sum())
    else:
        trend_streak = int((tail5["close"] < tail5["open"]).sum())

    if trend_streak >= 4:
        return False

    try:
        o, c, _, _ = _safe_candle_values(df, -1)
        if direction == "LONG" and c <= o:
            return False
        if direction == "SHORT" and c >= o:
            return False
    except ValueError:
        return False

    return True


def get_trend_tf(tf: str) -> str:
    if tf == "15m":
        return "1h"
    if tf == "1h":
        return "4h"
    return "4h"


def round_price(price: float) -> float:
    if price >= 1000:
        return round(price, 1)
    if price >= 100:
        return round(price, 2)
    if price >= 1:
        return round(price, 3)
    return round(price, 5)


def _tf_ms(tf: str) -> int:
    if tf.endswith("m"):
        return int(tf.replace("m", "")) * 60_000
    if tf.endswith("h"):
        return int(tf.replace("h", "")) * 3_600_000
    return 3_600_000


def _candle_progress(df: pd.DataFrame, tf: str) -> float:
    try:
        open_ms = int(df["time"].iloc[-1])
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        dur = _tf_ms(tf)
        if dur <= 0:
            return 0.0
        return max(0.0, min(1.5, (now_ms - open_ms) / dur))
    except Exception:
        return 0.0


def _chase_amount_atr(direction: str, price: float, candle_open: float, atr_val: float) -> float:
    if atr_val <= 0:
        return 0.0
    if direction == "LONG":
        return max(0.0, (price - candle_open) / atr_val)
    return max(0.0, (candle_open - price) / atr_val)


def _st_aligned(direction: str, st_dir: str) -> bool:
    return (direction == "LONG" and st_dir == "UP") or (direction == "SHORT" and st_dir == "DOWN")


def _compute_structural_sl_tp(
    *,
    direction: str,
    entry: float,
    atr_val: float,
    base_sl_mult: float,
    tp_mult: float,
    df: pd.DataFrame,
    lookback: int,
    buffer_atr: float,
    max_struct_sl_pct: float,
    absolute_max_sl_pct: float,
) -> Tuple[float, float]:
    if direction == "LONG":
        sl_atr = entry - base_sl_mult * atr_val
        tp_atr = entry + tp_mult * atr_val
    else:
        sl_atr = entry + base_sl_mult * atr_val
        tp_atr = entry - tp_mult * atr_val

    tail = df.tail(max(lookback, 3))

    if direction == "LONG":
        swing = float(tail["low"].min())
        sl_struct = swing - buffer_atr * atr_val
        candidate = min(sl_atr, sl_struct)
    else:
        swing = float(tail["high"].max())
        sl_struct = swing + buffer_atr * atr_val
        candidate = max(sl_atr, sl_struct)

    sl_pct = abs(entry - candidate) / entry if entry > 0 else 0.0

    if sl_pct > max_struct_sl_pct:
        candidate = sl_atr
        sl_pct = abs(entry - sl_atr) / entry

    if sl_pct > absolute_max_sl_pct:
        if direction == "LONG":
            candidate = entry * (1 - absolute_max_sl_pct)
        else:
            candidate = entry * (1 + absolute_max_sl_pct)

    return candidate, tp_atr


def _macd_aligned(direction: str, macd_ok: bool) -> bool:
    return (direction == "LONG" and macd_ok) or (direction == "SHORT" and (not macd_ok))


def _pattern_against(direction: str, pattern: Optional[str]) -> bool:
    if not pattern:
        return False
    if direction == "LONG" and pattern in BEARISH_PATTERNS:
        return True
    if direction == "SHORT" and pattern in BULLISH_PATTERNS:
        return True
    return False


def score_signal_lite(
    *,
    direction: str,
    rsi_val: float,
    macd_ok: bool,
    vol_ok: bool,
    pattern: Optional[str],
    candle_strong: bool,
    st_dir: str,
    htf_trend: str,
    atr_pct: float,
    tf: str,
    late_or_chase_penalty: bool,
) -> int:
    score = 55

    dist = abs(rsi_val - 50.0)
    score += int(max(0, 18 - dist * 0.7))

    score += 12 if _macd_aligned(direction, macd_ok) else -8
    score += 10 if vol_ok else -3
    score += 8 if candle_strong else -3

    htf_aligned = (
        (direction == "LONG" and htf_trend == "Long") or
        (direction == "SHORT" and htf_trend == "Short")
    )
    score += 5 if htf_aligned else -6

    score += 6 if _st_aligned(direction, st_dir) else -25

    if _pattern_against(direction, pattern):
        score -= 25
    elif pattern == "Doji":
        score -= 6
    elif pattern in STRUCT_PATTERNS:
        score += 6

    if tf == "15m":
        if LITE_15M_MIN_ATR_PCT <= atr_pct <= 0.020:
            score += 6
        elif atr_pct >= LITE_15M_MIN_ATR_PCT:
            score += 2
        else:
            score -= 10
    else:
        if LITE_MIN_ATR_PCT <= atr_pct <= 0.020:
            score += 6
        elif atr_pct >= LITE_MIN_ATR_PCT:
            score += 2
        else:
            score -= 10

    if tf == "1h" and late_or_chase_penalty:
        score -= ONE_H_PENALTY_SCORE

    score = max(0, min(int(round(score)), 100))

    if score >= 95:
        macd_confirm = _macd_aligned(direction, macd_ok)
        pattern_confirm = bool(pattern and pattern != "Doji" and pattern in STRUCT_PATTERNS)
        confirms = int(vol_ok) + int(macd_confirm) + int(pattern_confirm)
        if confirms < 2:
            score = 92

    if (not vol_ok) and score > NO_VOL_SCORE_CAP:
        score = NO_VOL_SCORE_CAP

    return score


def validate_rsi_gates(
    direction: str,
    rsi_val: float,
    timeframe: str,
    vol_ok: bool
) -> Tuple[bool, Optional[SignalRejectionReason]]:
    if timeframe in ("1h", "4h"):
        if direction == "LONG":
            if rsi_val < RSI_LONG_MIN or rsi_val > RSI_LONG_MAX:
                return False, SignalRejectionReason.RSI_HARD_BLOCK
        else:
            if rsi_val < RSI_SHORT_MIN or rsi_val > RSI_SHORT_MAX:
                return False, SignalRejectionReason.RSI_HARD_BLOCK

    elif timeframe == "15m":
        if direction == "LONG":
            if rsi_val > RSI_15M_LONG_MAX:
                return False, SignalRejectionReason.RSI_HARD_BLOCK
            if rsi_val < RSI_15M_LONG_MIN_SOFT and not vol_ok:
                return False, SignalRejectionReason.RSI_SAFETY
        else:
            if rsi_val < RSI_15M_SHORT_MIN:
                return False, SignalRejectionReason.RSI_HARD_BLOCK
            if rsi_val > RSI_15M_SHORT_MAX_SOFT and not vol_ok:
                return False, SignalRejectionReason.RSI_SAFETY

    return True, None


def count_confirmations(*, direction: str, macd_ok: bool, vol_ok: bool, pattern: Optional[str]) -> int:
    n = 0
    if vol_ok:
        n += 1
    if _macd_aligned(direction, macd_ok):
        n += 1
    if pattern and pattern != "Doji" and pattern in STRUCT_PATTERNS:
        n += 1
    return n


class MarketMode15M(str, Enum):
    NO_TRADE = "NO_TRADE"
    EXTREME_REVERSION = "EXTREME_REVERSION"
    IMPULSE_CONTINUATION = "IMPULSE_CONTINUATION"


def detect_market_mode_15m(
    *,
    df: pd.DataFrame,
    direction: str,
    rsi: float,
    atr_pct: float,
    vol_ok: bool,
    pattern: Optional[str],
    candle_strong: bool,
    st_dir: str,
) -> Tuple[MarketMode15M, str]:
    if direction == "LONG":
        if rsi <= 32 and vol_ok and (pattern in STRUCT_PATTERNS):
            return MarketMode15M.EXTREME_REVERSION, "extreme_reversion_long"
    else:
        if rsi >= 68 and vol_ok and (pattern in STRUCT_PATTERNS):
            return MarketMode15M.EXTREME_REVERSION, "extreme_reversion_short"

    pullback_ok = is_pullback_context_15m(df, direction, rsi)

    impulse_confirmed = (
        vol_ok and
        candle_strong and
        _st_aligned(direction, st_dir)
    )

    if pullback_ok and impulse_confirmed:
        return MarketMode15M.IMPULSE_CONTINUATION, "pullback_impulse"

    return MarketMode15M.NO_TRADE, "flat_no_impulse_no_extreme"


class MarketMode1H(str, Enum):
    NO_TRADE = "NO_TRADE"
    IMPULSE_CONFIRMED = "IMPULSE_CONFIRMED"


def detect_market_mode_1h(
    *,
    direction: str,
    rsi: float,
    vol_ok: bool,
    pattern: Optional[str],
    candle_strong: bool,
    st_dir: str,
    macd_ok: bool,
) -> Tuple[MarketMode1H, str]:
    st_ok = _st_aligned(direction, st_dir)
    impulse_confirmed = candle_strong and st_ok and (vol_ok or _macd_aligned(direction, macd_ok))
    if impulse_confirmed:
        return MarketMode1H.IMPULSE_CONFIRMED, "impulse_confirmed"
    return MarketMode1H.NO_TRADE, "no_impulse"


def _has_structure(pattern: Optional[str]) -> bool:
    return bool(pattern) and (pattern in STRUCT_PATTERNS) and (pattern != "Doji")


def get_signal(
    symbol: str,
    timeframe: str,
    *,
    min_score: int,
    vol_mult: float,
    red_threshold: int,
    allow_trend_fallback: bool,
) -> Optional[Signal]:
    rejection_reasons: List[str] = []

    def reject(reason: SignalRejectionReason) -> None:
        rejection_reasons.append(reason.value)

    df = fetch_klines(symbol, interval=timeframe, limit=200)
    if df is None or len(df) < 60:
        reject(SignalRejectionReason.INSUFFICIENT_DATA)
        return None

    trend_tf = get_trend_tf(timeframe)
    df_trend = fetch_klines(symbol, interval=trend_tf, limit=200)
    if df_trend is None or len(df_trend) < 60:
        reject(SignalRejectionReason.INSUFFICIENT_DATA)
        return None

    try:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        vol = df["volume"]

        rsi_val = float(round(compute_rsi(close, RSI_PERIOD).iloc[-1], 2))

        ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
        ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
        macd_ok = bool(ema_fast.iloc[-1] > ema_slow.iloc[-1])

        vol_ma = vol.rolling(VOL_WINDOW).mean()
        vol_ok = bool(vol_ma.iloc[-1] > 0 and vol.iloc[-1] > vol_ma.iloc[-1] * vol_mult)

        candle_strong = _candle_body_strong(df, -1)

        atr_val = float(compute_atr(high, low, close, ATR_PERIOD).iloc[-1])
        price = float(close.iloc[-1])
        atr_pct = (atr_val / price) if price > 0 else 0.0

        _, st_dir = compute_supertrend(df)

        htf_close = df_trend["close"]
        htf_mean = htf_close.rolling(50).mean().fillna(htf_close.mean())
        htf_trend = "Long" if htf_close.iloc[-1] > htf_mean.iloc[-1] else "Short"

        pattern = detect_pattern(df, float(vol_ma.iloc[-1]), float(vol.iloc[-1]))

    except Exception as e:
        logger.error(f"{symbol}/{timeframe}: Indicator calculation error: {e}", exc_info=True)
        reject(SignalRejectionReason.API_ERROR)
        return None

    is_lite = bool(allow_trend_fallback)

    candle_open_time_ms = int(df["time"].iloc[-1])
    candle_close_time_ms = candle_open_time_ms + _tf_ms(timeframe) - 1

    # ATR filters
    if is_lite:
        if timeframe == "15m":
            if atr_pct < LITE_15M_MIN_ATR_PCT:
                reject(SignalRejectionReason.ATR_TOO_LOW)
                return None
            if atr_pct > LITE_15M_MAX_ATR_PCT:
                reject(SignalRejectionReason.ATR_TOO_HIGH)
                return None
        else:
            if atr_pct < LITE_MIN_ATR_PCT:
                reject(SignalRejectionReason.ATR_TOO_LOW)
                return None
            if atr_pct > LITE_MAX_ATR_PCT:
                reject(SignalRejectionReason.ATR_TOO_HIGH)
                return None

    if is_lite and timeframe == "15m" and atr_pct < LITE_MIN_ATR_PCT:
        has_confirm = bool(vol_ok) or _has_structure(pattern)
        if not has_confirm:
            reject(SignalRejectionReason.ATR_TOO_LOW)
            return None

    # Direction
    if is_lite:
        if timeframe == "1h":
            # меняем только 1h: направление по HTF
            direction = "LONG" if htf_trend == "Long" else "SHORT"
        elif timeframe == "15m":
            # 15m оставляем по старому поведению: направление по ST
            if st_dir == "UP":
                direction = "LONG"
            elif st_dir == "DOWN":
                direction = "SHORT"
            else:
                return None
        else:
            # 4h оставляем как было в текущей ветке
            direction = "LONG" if htf_trend == "Long" else "SHORT"
    else:
        if rsi_val < 45 and macd_ok:
            direction = "LONG"
        elif rsi_val > 55 and (not macd_ok):
            direction = "SHORT"
        else:
            return None

    signal_id = f"{symbol}:{timeframe}:{candle_open_time_ms}:{direction}"

    # 15m — НЕ ТРОГАЕМ
    if timeframe == "15m":
        mode15, _ = detect_market_mode_15m(
            df=df,
            direction=direction,
            rsi=rsi_val,
            atr_pct=atr_pct,
            vol_ok=vol_ok,
            pattern=pattern,
            candle_strong=candle_strong,
            st_dir=st_dir,
        )
        if mode15 == MarketMode15M.NO_TRADE:
            reject(SignalRejectionReason.MARKET_MODE_15M_NO_TRADE)
            return None

    confirmations_count: Optional[int] = None
    market_mode: Optional[str] = None
    market_mode_pre: Optional[str] = None
    market_mode_post: Optional[str] = None
    candle_progress: Optional[float] = None
    chase_atr: Optional[float] = None
    anti_late_blocked: Optional[bool] = None
    reversal_attempted: bool = False

    # 1h — МЕНЯЕМ ТОЛЬКО ЭТОТ БЛОК
    if timeframe == "1h" and is_lite:
        direction = "LONG" if htf_trend == "Long" else "SHORT"
        signal_id = f"{symbol}:{timeframe}:{candle_open_time_ms}:{direction}"

        candle_progress = _candle_progress(df, timeframe)
        candle_open = float(df["open"].iloc[-1])
        chase_atr = _chase_amount_atr(direction, price, candle_open, atr_val)

        mm1h, mm1h_reason = detect_market_mode_1h(
            direction=direction,
            rsi=rsi_val,
            vol_ok=vol_ok,
            pattern=pattern,
            candle_strong=candle_strong,
            st_dir=st_dir,
            macd_ok=macd_ok,
        )
        market_mode = f"{mm1h.value}:{mm1h_reason}"
        market_mode_pre = market_mode
        market_mode_post = market_mode

        confirmations_count = count_confirmations(
            direction=direction,
            macd_ok=macd_ok,
            vol_ok=vol_ok,
            pattern=pattern,
        )

        anti_late_blocked = False
        reversal_attempted = False

    # RSI gates
    if is_lite:
        rsi_valid, _ = validate_rsi_gates(direction, rsi_val, timeframe, vol_ok)
        if not rsi_valid:
            reject(SignalRejectionReason.RSI_HARD_BLOCK)
            return None

        if _pattern_against(direction, pattern):
            reject(SignalRejectionReason.PATTERN_AGAINST)
            return None

        if timeframe != "15m":
            if (not vol_ok) and (not candle_strong):
                reject(SignalRejectionReason.NO_VOLUME_WEAK_CANDLE)
                return None

    htf_aligned = (
        (direction == "LONG" and htf_trend == "Long") or
        (direction == "SHORT" and htf_trend == "Short")
    )
    reason = "trend"

    late_or_chase_penalty = False
    if timeframe == "1h" and is_lite and candle_progress is not None and chase_atr is not None:
        if candle_progress > 0.60 or chase_atr > 0.90:
            late_or_chase_penalty = True

    score = score_signal_lite(
        direction=direction,
        rsi_val=rsi_val,
        macd_ok=macd_ok,
        vol_ok=vol_ok,
        pattern=pattern,
        candle_strong=candle_strong,
        st_dir=st_dir,
        htf_trend=htf_trend,
        atr_pct=atr_pct,
        tf=timeframe,
        late_or_chase_penalty=late_or_chase_penalty,
    )

    if score < min_score:
        reject(SignalRejectionReason.LOW_SCORE)
        return None

    if red_threshold and score < red_threshold:
        reject(SignalRejectionReason.LOW_SCORE)
        return None

    entry = round_price(price)
    sl_mult = (LITE_SL_MULT if is_lite else SL_R_MULT)

    if is_lite and timeframe == "1h":
        sl_raw, tp_raw = _compute_structural_sl_tp(
            direction=direction,
            entry=entry,
            atr_val=atr_val,
            base_sl_mult=sl_mult,
            tp_mult=TP_R_MULT,
            df=df,
            lookback=ONE_H_SWING_LOOKBACK,
            buffer_atr=ONE_H_STRUCT_BUFFER_ATR,
            max_struct_sl_pct=ONE_H_MAX_STRUCT_SL_PCT,
            absolute_max_sl_pct=ONE_H_ABSOLUTE_MAX_SL_PCT,
        )
    else:
        if direction == "LONG":
            sl_raw = entry - sl_mult * atr_val
            tp_raw = entry + TP_R_MULT * atr_val
        else:
            sl_raw = entry + sl_mult * atr_val
            tp_raw = entry - TP_R_MULT * atr_val

    tp = round_price(tp_raw)
    sl = round_price(sl_raw)
    sl_pct = abs(entry - sl) / entry if entry > 0 else 0.0

    if timeframe == "15m" and sl_pct < MIN_SL_PCT_15M:
        reject(SignalRejectionReason.SL_TOO_TIGHT)
        return None

    if is_lite and sl_pct > ONE_H_ABSOLUTE_MAX_SL_PCT:
        reject(SignalRejectionReason.SL_TOO_WIDE)
        return None

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    confidence_factors = {
        "vol_confirmed": vol_ok,
        "pattern_aligned": bool(pattern and not _pattern_against(direction, pattern)),
        "htf_aligned": htf_aligned,
        "st_aligned": _st_aligned(direction, st_dir),
        "rsi_optimal": 40 <= rsi_val <= 60,
        "atr_optimal": (
            (timeframe == "15m" and LITE_15M_MIN_ATR_PCT <= atr_pct <= 0.020) or
            (timeframe != "15m" and LITE_MIN_ATR_PCT <= atr_pct <= 0.020)
        ),
        "late_or_chase_penalty": late_or_chase_penalty,
    }

    logger.info(
        f"✅ Signal generated: {signal_id} {symbol} {direction} {timeframe} "
        f"(score={score}, RSI={rsi_val}, pattern={pattern}, ST={st_dir}, HTF={htf_trend}, reason={reason})"
    )

    return Signal(
        symbol=symbol,
        timeframe=timeframe,
        direction=direction,
        entry=entry,
        tp=tp,
        sl=sl,
        score=int(score),
        rsi=rsi_val,
        macd=macd_ok,
        volume=vol_ok,
        pattern=pattern,
        trend_htf=htf_trend,
        reason=reason,
        candle_body=candle_strong,
        atr=atr_val,
        atr_pct=atr_pct,
        supertrend_dir=st_dir,
        sl_pct=sl_pct,
        timestamp=ts,
        signal_id=signal_id,
        candle_open_time_ms=candle_open_time_ms,
        candle_close_time_ms=candle_close_time_ms,
        confirmations_count=confirmations_count,
        market_mode=market_mode,
        market_mode_pre=market_mode_pre,
        market_mode_post=market_mode_post,
        candle_progress=candle_progress,
        chase_atr=chase_atr,
        anti_late_blocked=anti_late_blocked,
        reversal_attempted=reversal_attempted,
        rejection_reasons=rejection_reasons or None,
        confidence_factors=confidence_factors,
    )


def classify_signal_strength(score: int, vol_ok: bool, pattern: Optional[str]) -> Tuple[str, str]:
    has_pattern = bool(pattern) and pattern != "Doji"
    is_impulse = bool(vol_ok) or has_pattern

    if score >= 98:
        if is_impulse:
            return "🔵", "Премиум"
        return "🟣", "Структура"

    if score >= 90:
        if is_impulse:
            return "🔥", "Импульс"
        return "🟢", "Сильный"

    if score >= 80:
        return "🟢", "Сильный"

    if score >= 70:
        return "🟡", "Рабочий"

    return "⚫️", "Слабый"


def format_bool_flag(val: bool) -> str:
    return "Да ✅" if val else "Нет ❌"


def format_trend_label(trend_htf: str) -> str:
    if trend_htf == "Long":
        return "Long ↗️"
    if trend_htf == "Short":
        return "Short ↘️"
    return trend_htf


def format_supertrend_label(st_dir: str) -> str:
    if st_dir == "UP":
        return "UP ↗️"
    if st_dir == "DOWN":
        return "DOWN ↘️"
    return st_dir


def format_signal_text(signal: Signal, *, mode: str) -> str:
    dir_emoji = "📈" if signal.direction == "LONG" else "📉"

    strength_emoji, strength_label = classify_signal_strength(
        signal.score, signal.volume, signal.pattern
    )
    atr_pct_str = f"{signal.atr_pct * 100:.2f}%"

    trend_label = format_trend_label(signal.trend_htf)
    st_label = format_supertrend_label(signal.supertrend_dir)
    pattern_str = signal.pattern if signal.pattern else "Нет"

    header = f"{signal.symbol} — {signal.direction} ({signal.timeframe}) {dir_emoji}"

    price_block = (
        f"Цена: {signal.entry}\n"
        f"TP: {signal.tp} | SL: {signal.sl}"
    )

    quality_block = f"Качество сигнала: {signal.score}/100 {strength_emoji} {strength_label}"

    indicators_block = (
        f"RSI: {signal.rsi}\n"
        f"MACD: {format_bool_flag(signal.macd)}\n"
        f"Объём: {format_bool_flag(signal.volume)}\n"
        f"Паттерн: {pattern_str}\n"
        f"Тренд HTF: {trend_label}\n"
        f"SuperTrend: {st_label}\n"
        f"Свеча: {'Сильная' if signal.candle_body else 'Обычная'}\n"
        f"ATR: {atr_pct_str}"
    )

    risk_block = f"📍 SL-дистанция: {signal.sl_pct * 100:.2f}%"

    return (
        f"{header}\n\n"
        f"{price_block}\n\n"
        f"{quality_block}\n\n"
        f"{indicators_block}\n"
        f"{risk_block}"
    )
