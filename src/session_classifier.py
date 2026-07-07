from __future__ import annotations

from typing import Any

import pandas as pd

SESSION_ALIASES = {
    "ASIA": "ASIA",
    "EUROPE": "EUROPE",
    "EU": "EUROPE",
    "LONDON": "EUROPE",
    "US": "US",
    "USA": "US",
    "NY": "US",
    "NEW_YORK": "US",
    "OVERLAP": "OVERLAP",
    "EU_US": "OVERLAP",
    "EU_US_OVERLAP": "OVERLAP",
}


def normalize_session(value: Any) -> str:
    if value is None or pd.isna(value):
        return "UNKNOWN"
    raw = str(value).strip().upper().replace(" ", "_").replace("-", "_")
    return SESSION_ALIASES.get(raw, raw if raw in {"ASIA", "EUROPE", "US", "OVERLAP"} else "UNKNOWN")


def classify_by_hour_msk(value: Any) -> str:
    if value is None or pd.isna(value):
        return "UNKNOWN"
    try:
        hour = int(float(value))
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not 0 <= hour <= 23:
        return "UNKNOWN"
    if 0 <= hour < 8:
        return "ASIA"
    if 8 <= hour < 16:
        return "EUROPE"
    if 16 <= hour < 19:
        return "OVERLAP"
    if 19 <= hour < 24:
        return "US"
    return "UNKNOWN"


def classify_session(row: pd.Series) -> str:
    session = normalize_session(row.get("session_msk"))
    if session != "UNKNOWN":
        return session
    return classify_by_hour_msk(row.get("hour_msk"))
