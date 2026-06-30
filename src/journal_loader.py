from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

RESULT_MAP = {
    "TP": "win",
    "WIN": "win",
    "PROFIT": "win",
    "TAKE_PROFIT": "win",
    "TAKE PROFIT": "win",
    "SL": "loss",
    "LOSS": "loss",
    "STOP_LOSS": "loss",
    "STOP LOSS": "loss",
}

COLUMN_ALIASES = {
    "time_frame": "timeframe",
    "tf": "timeframe",
    "take_profit": "tp",
    "stop_loss": "sl",
    "stoploss": "sl",
    "market_mode": "market_phase",
    "pattern": "setup_type",
    "supertrend": "supertrend_dir",
    "created_at_moscow": "created_at_msk",
}


def normalize_column_name(name: Any) -> str:
    normalized = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return COLUMN_ALIASES.get(normalized, normalized)


def normalize_result(value: Any) -> str | None:
    if pd.isna(value):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return RESULT_MAP.get(raw.upper(), raw.lower())


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _calculate_r(row: pd.Series, warnings: list[str]) -> float | None:
    result = row.get("result_normalized")
    if result == "loss":
        return -1.0
    if result != "win":
        return None

    entry = _safe_float(row.get("entry"))
    tp = _safe_float(row.get("tp"))
    sl = _safe_float(row.get("sl"))
    if entry is None or tp is None or sl is None:
        warnings.append("Cannot calculate R for some winning rows: entry/tp/sl missing.")
        return None

    risk = abs(entry - sl)
    if risk == 0:
        warnings.append("Cannot calculate R for some winning rows: entry equals sl.")
        return None
    return abs(tp - entry) / risk


def load_journal_csv(path: str | Path, timeframe: str = "15m") -> tuple[pd.DataFrame, list[str]]:
    csv_path = Path(path)
    warnings: list[str] = []
    if not csv_path.exists():
        raise FileNotFoundError(f"Journal CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    original_columns = list(df.columns)
    base_names = {str(col).strip().lower().replace(" ", "_").replace("-", "_") for col in df.columns}
    rename_map = {}
    for col in df.columns:
        base = str(col).strip().lower().replace(" ", "_").replace("-", "_")
        alias = COLUMN_ALIASES.get(base)
        if alias and alias in base_names:
            rename_map[col] = base
        else:
            rename_map[col] = normalize_column_name(col)
    df = df.rename(columns=rename_map)
    df.attrs["original_columns"] = original_columns
    df.attrs["normalized_columns"] = list(df.columns)

    if "timeframe" in df.columns:
        df = df[df["timeframe"].astype(str).str.lower() == timeframe.lower()].copy()
    else:
        warnings.append("Column 'timeframe' missing; timeframe filter was skipped.")

    if "result" in df.columns:
        df["result_normalized"] = df["result"].map(normalize_result)
    else:
        df["result_normalized"] = None
        warnings.append("Column 'result' missing; win/loss metrics will be incomplete.")

    missing_r_cols = [col for col in ("entry", "tp", "sl") if col not in df.columns]
    if missing_r_cols:
        warnings.append(f"Columns missing for R calculation: {', '.join(missing_r_cols)}.")

    df["r"] = df.apply(lambda row: _calculate_r(row, warnings), axis=1)
    warnings = list(dict.fromkeys(warnings))
    return df.reset_index(drop=True), warnings
