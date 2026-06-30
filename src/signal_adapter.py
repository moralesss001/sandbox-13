from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .journal_loader import load_journal_csv, normalize_result
from .order_models import SignalCandidate
from .session_classifier import classify_session


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_text(value: Any, default: str = "UNKNOWN") -> str:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return default
    return str(value).strip()


def signals_from_journal(file_path: str | Path, timeframe: str = "15m") -> tuple[list[SignalCandidate], list[str]]:
    df, warnings = load_journal_csv(file_path, timeframe=timeframe)
    signals: list[SignalCandidate] = []
    for _, row in df.iterrows():
        result = normalize_result(row.get("result_normalized") or row.get("result"))
        if result not in {"win", "loss"}:
            continue
        entry = _safe_float(row.get("entry"))
        tp = _safe_float(row.get("tp"))
        sl = _safe_float(row.get("sl"))
        if entry is None or tp is None or sl is None:
            continue
        session = classify_session(row)
        signals.append(
            SignalCandidate(
                symbol=_safe_text(row.get("symbol"), "UNKNOWN"),
                timeframe=_safe_text(row.get("timeframe"), timeframe),
                direction=_safe_text(row.get("direction"), "LONG").upper(),
                entry=entry,
                tp=tp,
                sl=sl,
                rr_ratio=float(_safe_float(row.get("rr_ratio"), 1.5) or 1.5),
                created_at=_safe_text(row.get("created_at"), datetime.now(timezone.utc).isoformat()),
                rsi=_safe_float(row.get("rsi")),
                atr_pct=_safe_float(row.get("atr_pct")),
                market_phase=_safe_text(row.get("market_phase"), "UNKNOWN"),
                session=session,
                setup_type=_safe_text(row.get("setup_type"), _safe_text(row.get("pattern"), "UNKNOWN")),
                trend_htf=_safe_text(row.get("trend_htf"), "UNKNOWN"),
                reason=_safe_text(row.get("reason"), ""),
                confidence_factors=row.get("confidence_factors"),
                signal_source="journal_replay",
                source=str(file_path),
                result=result,
                historical_r=_safe_float(row.get("r")),
                raw=row.to_dict(),
            )
        )
    return signals, warnings


def _rsi(closes: pd.Series, period: int = 14) -> float:
    delta = closes.astype(float).diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    value = 100 - (100 / (1 + rs.iloc[-1])) if len(rs.dropna()) else 50.0
    return float(value) if pd.notna(value) else 50.0


def _atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    last_close = close.iloc[-1]
    return float(atr / last_close) if pd.notna(atr) and last_close else 0.0


def signal_from_klines(symbol: str, timeframe: str, klines: pd.DataFrame) -> SignalCandidate | None:
    if klines.empty or len(klines) < 20:
        return None
    work = klines.copy()
    for column in ["open", "high", "low", "close"]:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    last = work.iloc[-1]
    closes = work["close"]
    last_close = float(last["close"])
    ma_fast = float(closes.tail(5).mean())
    ma_slow = float(closes.tail(20).mean())
    direction = "LONG" if ma_fast >= ma_slow else "SHORT"
    atr_pct = _atr_pct(work)
    risk_distance = max(last_close * max(atr_pct, 0.005), last_close * 0.003)
    if direction == "LONG":
        sl = last_close - risk_distance
        tp = last_close + risk_distance * 1.5
    else:
        sl = last_close + risk_distance
        tp = last_close - risk_distance * 1.5
    return SignalCandidate(
        symbol=symbol.upper(),
        timeframe=timeframe,
        direction=direction,
        entry=last_close,
        tp=tp,
        sl=sl,
        rr_ratio=1.5,
        created_at=datetime.now(timezone.utc).isoformat(),
        rsi=_rsi(closes),
        atr_pct=atr_pct,
        market_phase="trend" if abs(ma_fast - ma_slow) / last_close > 0.002 else "unclear",
        session="LIVE",
        setup_type="continuation" if abs(ma_fast - ma_slow) / last_close > 0.002 else "rebound",
        trend_htf="aligned" if ma_fast >= ma_slow else "countertrend",
        reason="simplified_ma_atr_signal",
        signal_source="research_simplified_live",
        source="binance_public_rest",
        raw=last.to_dict(),
    )
