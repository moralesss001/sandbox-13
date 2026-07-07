from __future__ import annotations

from typing import Iterable

import pandas as pd

MIN_COMBINATION_TRADES = 3


def _closed(df: pd.DataFrame) -> pd.DataFrame:
    if "result_normalized" not in df.columns:
        return df.iloc[0:0].copy()
    return df[df["result_normalized"].isin(["win", "loss"])].copy()


def _r_series(df: pd.DataFrame) -> pd.Series:
    if "r" not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df["r"], errors="coerce").dropna()


def _session_column(df: pd.DataFrame) -> str:
    if "session_shadow" in df.columns:
        return "session_shadow"
    return "session_msk"


def _normalize_group_values(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    work = df.copy()
    for column in columns:
        if column in work.columns:
            work[column] = work[column].fillna("UNKNOWN").astype(str)
    return work


def combination_stats(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    closed = _closed(df)
    if closed.empty or any(column not in closed.columns for column in columns):
        return pd.DataFrame(
            columns=columns + ["combination", "trades", "wins", "losses", "winrate", "avg_R", "expectancy", "net_R"]
        )

    work = _normalize_group_values(closed, columns)
    rows = []
    for keys, group in work.groupby(columns, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        wins = int((group["result_normalized"] == "win").sum())
        losses = int((group["result_normalized"] == "loss").sum())
        r_values = _r_series(group)
        avg_r = float(r_values.mean()) if len(r_values) else 0.0
        net_r = float(r_values.sum()) if len(r_values) else 0.0
        row = {column: key for column, key in zip(columns, keys)}
        row.update(
            {
                "combination": " + ".join(str(key) for key in keys),
                "trades": int(len(group)),
                "wins": wins,
                "losses": losses,
                "winrate": float(wins / len(group) * 100) if len(group) else 0.0,
                "avg_R": avg_r,
                "expectancy": avg_r,
                "net_R": net_r,
            }
        )
        rows.append(row)

    return pd.DataFrame(rows).sort_values(["net_R", "trades"], ascending=[True, False]).reset_index(drop=True)


def rr_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    if "rr_ratio" not in df.columns:
        return pd.DataFrame(columns=["rr_ratio", "combination", "trades", "wins", "losses", "winrate", "avg_R", "net_R"])

    work = df.copy()
    rr = pd.to_numeric(work["rr_ratio"], errors="coerce")
    if rr.dropna().empty:
        return pd.DataFrame(columns=["rr_ratio", "combination", "trades", "wins", "losses", "winrate", "avg_R", "net_R"])

    work["rr_ratio"] = rr.map(lambda value: f"RR {value:.1f}" if pd.notna(value) else "UNKNOWN")
    stats = combination_stats(work, ["rr_ratio"])
    return stats[["rr_ratio", "combination", "trades", "wins", "losses", "winrate", "avg_R", "net_R"]]


def _ranked(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["rank", "combination", "trades", "winrate", "net_R"])
    ranked = df.copy().reset_index(drop=True)
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return ranked[["rank", "combination", "trades", "winrate", "net_R"]]


def find_toxic_combinations(df: pd.DataFrame, min_trades: int = MIN_COMBINATION_TRADES) -> pd.DataFrame:
    level_3 = combination_stats(df, ["market_phase", _session_column(df), "setup_type"])
    if level_3.empty:
        return _ranked(level_3)
    toxic = level_3[(level_3["trades"] >= min_trades) & ((level_3["winrate"] < 35) | (level_3["net_R"] < -2))]
    toxic = toxic.sort_values(["net_R", "winrate", "trades"], ascending=[True, True, False])
    return _ranked(toxic)


def find_positive_combinations(df: pd.DataFrame, min_trades: int = MIN_COMBINATION_TRADES) -> pd.DataFrame:
    level_3 = combination_stats(df, ["market_phase", _session_column(df), "setup_type"])
    if level_3.empty:
        return _ranked(level_3)
    positive = level_3[(level_3["trades"] >= min_trades) & ((level_3["winrate"] > 65) | (level_3["net_R"] > 2))]
    positive = positive.sort_values(["net_R", "winrate", "trades"], ascending=[False, False, False])
    return _ranked(positive)


def build_combination_analysis(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    session_col = _session_column(df)
    return {
        "phase_session": combination_stats(df, ["market_phase", session_col]),
        "phase_session_setup": combination_stats(df, ["market_phase", session_col, "setup_type"]),
        "phase_rsi": combination_stats(df, ["market_phase", "rsi_zone"]),
        "phase_session_rsi": combination_stats(df, ["market_phase", session_col, "rsi_zone"]),
        "rr_ratio": rr_breakdown(df),
        "toxic_combinations": find_toxic_combinations(df),
        "positive_combinations": find_positive_combinations(df),
    }


def build_combination_insights(analysis: dict[str, pd.DataFrame]) -> list[str]:
    insights: list[str] = []
    toxic = analysis.get("toxic_combinations", pd.DataFrame())
    positive = analysis.get("positive_combinations", pd.DataFrame())

    if toxic is not None and not toxic.empty:
        first = toxic.iloc[0]
        insights.append(
            "Most toxic cluster: "
            f"{first['combination']} | Trades: {int(first['trades'])} | "
            f"Winrate: {first['winrate']:.2f}% | Net R: {first['net_R']:.2f}"
        )
    else:
        insights.append("No toxic level-3 cluster met the minimum sample threshold.")

    if positive is not None and not positive.empty:
        first = positive.iloc[0]
        insights.append(
            "Strongest positive cluster: "
            f"{first['combination']} | Trades: {int(first['trades'])} | "
            f"Winrate: {first['winrate']:.2f}% | Net R: {first['net_R']:.2f}"
        )
    else:
        insights.append("No positive level-3 cluster met the minimum sample threshold.")

    insights.append("These are research statistics only; no automatic filter or production rule is applied.")
    return insights
