from __future__ import annotations

from typing import Any

import pandas as pd

from .models import MarketContext


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_rsi_zone(rsi: Any) -> str:
    value = _safe_float(rsi)
    if value is None:
        return "UNKNOWN"
    if value < 35:
        return "LOW"
    if value <= 65:
        return "MID"
    return "HIGH"


def classify_volatility_state(atr_pct: Any) -> str:
    value = _safe_float(atr_pct)
    if value is None:
        return "UNKNOWN"
    if value < 0.45:
        return "LOW_VOL"
    if value <= 0.8:
        return "NORMAL_VOL"
    return "HIGH_VOL"


def build_market_context(row: pd.Series) -> MarketContext:
    warnings: list[str] = []
    if "rsi" not in row.index:
        warnings.append("Column 'rsi' missing; rsi_zone=UNKNOWN.")
    if "atr_pct" not in row.index:
        warnings.append("Column 'atr_pct' missing; volatility_state=UNKNOWN.")

    rr_ratio = _safe_float(row.get("rr_ratio"))
    return MarketContext(
        rsi_zone=classify_rsi_zone(row.get("rsi")),
        volatility_state=classify_volatility_state(row.get("atr_pct")),
        market_phase=str(row.get("market_phase") or "UNKNOWN").strip() or "UNKNOWN",
        setup_type=str(row.get("setup_type") or "UNKNOWN").strip() or "UNKNOWN",
        trend_htf=str(row.get("trend_htf") or "UNKNOWN").strip() or "UNKNOWN",
        impulse_before_entry=row.get("impulse_before_entry"),
        reason=row.get("reason"),
        confidence_factors=row.get("confidence_factors"),
        rr_ratio=rr_ratio,
        warnings=warnings,
    )
