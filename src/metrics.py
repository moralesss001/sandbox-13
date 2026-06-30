from __future__ import annotations

from typing import Any

import pandas as pd


def _closed(df: pd.DataFrame) -> pd.DataFrame:
    if "result_normalized" not in df.columns:
        return df.iloc[0:0].copy()
    return df[df["result_normalized"].isin(["win", "loss"])].copy()


def _r_series(df: pd.DataFrame) -> pd.Series:
    if "r" not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df["r"], errors="coerce").dropna()


def baseline_metrics(df: pd.DataFrame) -> dict[str, Any]:
    closed = _closed(df)
    wins = closed[closed["result_normalized"] == "win"]
    losses = closed[closed["result_normalized"] == "loss"]
    r_values = _r_series(closed)
    gross_win_r = float(_r_series(wins).sum())
    gross_loss_r = abs(float(_r_series(losses).sum()))

    return {
        "total_trades": int(len(closed)),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "winrate": float(len(wins) / len(closed) * 100) if len(closed) else 0.0,
        "profit_factor": float(gross_win_r / gross_loss_r) if gross_loss_r else None,
        "expectancy": float(r_values.mean()) if len(r_values) else 0.0,
        "avg_R": float(r_values.mean()) if len(r_values) else 0.0,
        "gross_win_R": gross_win_r,
        "gross_loss_R": gross_loss_r,
    }


def shadow_effect(df: pd.DataFrame) -> dict[str, Any]:
    closed = _closed(df)
    blocked = closed[closed["decision_shadow"] == "NO_TRADE"] if "decision_shadow" in closed else closed.iloc[0:0]
    blocked_losses = blocked[blocked["result_normalized"] == "loss"]
    missed_wins = blocked[blocked["result_normalized"] == "win"]
    blocked_losses_r = abs(float(_r_series(blocked_losses).sum()))
    missed_wins_r = float(_r_series(missed_wins).sum())
    return {
        "blocked_losses_count": int(len(blocked_losses)),
        "blocked_losses_R": blocked_losses_r,
        "missed_wins_count": int(len(missed_wins)),
        "missed_wins_R": missed_wins_r,
        "net_effect_R": blocked_losses_r - missed_wins_r,
    }


def breakdown(df: pd.DataFrame, column: str) -> pd.DataFrame:
    closed = _closed(df)
    if column not in closed.columns or closed.empty:
        return pd.DataFrame(columns=[column, "trades", "wins", "losses", "avg_R", "net_R", "winrate"])

    work = closed.copy()
    work[column] = work[column].fillna("UNKNOWN").astype(str)
    rows = []
    for value, group in work.groupby(column, dropna=False):
        wins = int((group["result_normalized"] == "win").sum())
        losses = int((group["result_normalized"] == "loss").sum())
        r_values = _r_series(group)
        rows.append(
            {
                column: value,
                "trades": int(len(group)),
                "wins": wins,
                "losses": losses,
                "avg_R": float(r_values.mean()) if len(r_values) else 0.0,
                "net_R": float(r_values.sum()) if len(r_values) else 0.0,
                "winrate": float(wins / len(group) * 100) if len(group) else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values(["net_R", "trades"], ascending=[True, False]).reset_index(drop=True)


def all_breakdowns(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    columns = [
        "market_phase",
        "session_shadow",
        "setup_type",
        "rsi_zone",
        "volatility_state",
        "strategy_mode_shadow",
        "risk_mode_shadow",
        "decision_shadow",
    ]
    return {column: breakdown(df, column) for column in columns}


def top_toxic_combinations(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    closed = _closed(df)
    cols = [col for col in ["market_phase", "session_shadow", "setup_type"] if col in closed.columns]
    if not cols or closed.empty:
        return pd.DataFrame(columns=cols + ["trades", "net_R", "winrate"])

    work = closed.copy()
    for col in cols:
        work[col] = work[col].fillna("UNKNOWN").astype(str)

    rows = []
    for keys, group in work.groupby(cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        r_values = _r_series(group)
        wins = int((group["result_normalized"] == "win").sum())
        row = {col: key for col, key in zip(cols, keys)}
        row.update(
            {
                "trades": int(len(group)),
                "net_R": float(r_values.sum()) if len(r_values) else 0.0,
                "winrate": float(wins / len(group) * 100) if len(group) else 0.0,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["net_R", "trades"], ascending=[True, False]).head(limit)


def calculate_metrics(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "baseline": baseline_metrics(df),
        "shadow_effect": shadow_effect(df),
        "breakdowns": all_breakdowns(df),
        "top_toxic_combinations": top_toxic_combinations(df),
    }
