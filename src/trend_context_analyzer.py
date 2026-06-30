from __future__ import annotations

from typing import Iterable

import pandas as pd

from .cluster_validator import confidence_for_trades


def _closed(df: pd.DataFrame) -> pd.DataFrame:
    if "result_normalized" not in df.columns:
        return df.iloc[0:0].copy()
    return df[df["result_normalized"].isin(["win", "loss"])].copy()


def _r_series(df: pd.DataFrame) -> pd.Series:
    if "r" not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df["r"], errors="coerce").dropna()


def normalize_trend_htf(value) -> str:
    if value is None or pd.isna(value):
        return "unknown"
    raw = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    bullish = {"bullish", "bull", "long", "up", "trend_up", "uptrend"}
    bearish = {"bearish", "bear", "short", "down", "trend_down", "downtrend"}
    neutral = {"neutral", "flat", "range", "sideways", "none"}
    if raw in bullish:
        return "bullish"
    if raw in bearish:
        return "bearish"
    if raw in neutral:
        return "neutral"
    return "unknown"


def htf_alignment(direction, trend_htf: str) -> str:
    if trend_htf not in {"bullish", "bearish", "neutral"}:
        return "unknown"
    if trend_htf == "neutral":
        return "neutral"
    raw_direction = str(direction or "").strip().upper()
    if raw_direction == "LONG" and trend_htf == "bullish":
        return "aligned"
    if raw_direction == "SHORT" and trend_htf == "bearish":
        return "aligned"
    if raw_direction in {"LONG", "SHORT"}:
        return "countertrend"
    return "unknown"


def add_htf_context(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "trend_htf" in work.columns:
        work["trend_htf_normalized"] = work["trend_htf"].map(normalize_trend_htf)
    else:
        work["trend_htf_normalized"] = "unknown"
    if "direction" in work.columns:
        work["htf_alignment_score"] = work.apply(
            lambda row: htf_alignment(row.get("direction"), row.get("trend_htf_normalized")),
            axis=1,
        )
    else:
        work["htf_alignment_score"] = "unknown"
    return work


def _normalize_group_values(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    work = df.copy()
    for column in columns:
        if column in work.columns:
            work[column] = work[column].fillna("unknown").astype(str)
    return work


def grouped_stats(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    closed = _closed(add_htf_context(df))
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
        rows.append(
            {
                **{column: key for column, key in zip(columns, keys)},
                "combination": " + ".join(str(key) for key in keys),
                "trades": int(len(group)),
                "wins": wins,
                "losses": losses,
                "winrate": float(wins / len(group) * 100) if len(group) else 0.0,
                "avg_R": avg_r,
                "expectancy": avg_r,
                "net_R": float(r_values.sum()) if len(r_values) else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values(["net_R", "trades"], ascending=[True, False]).reset_index(drop=True)


def _with_confidence(stats: pd.DataFrame) -> pd.DataFrame:
    if stats.empty:
        return stats.assign(confidence=pd.Series(dtype=str))
    work = stats.copy()
    work["confidence"] = work["trades"].map(lambda trades: confidence_for_trades(int(trades)))
    return work


def htf_cluster_analysis(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    level_4 = _with_confidence(
        grouped_stats(df, ["market_phase", "session_shadow", "setup_type", "trend_htf_normalized"])
    )
    if level_4.empty:
        return level_4
    return level_4[["combination", "trades", "winrate", "expectancy", "net_R", "confidence"]].head(limit)


def htf_positive_clusters(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    level_4 = _with_confidence(
        grouped_stats(df, ["market_phase", "session_shadow", "setup_type", "trend_htf_normalized"])
    )
    if level_4.empty:
        return level_4
    positive = level_4.sort_values(["net_R", "trades"], ascending=[False, False])
    return positive[["combination", "trades", "winrate", "expectancy", "net_R", "confidence"]].head(limit)


def alignment_analysis(df: pd.DataFrame) -> pd.DataFrame:
    stats = grouped_stats(df, ["htf_alignment_score"])
    if stats.empty:
        return stats
    return stats[["htf_alignment_score", "trades", "winrate", "expectancy", "net_R"]]


def build_htf_impact_report(analysis: dict[str, pd.DataFrame]) -> list[str]:
    insights: list[str] = []
    phase_session_trend = analysis.get("phase_session_trend", pd.DataFrame())
    htf_breakdown = analysis.get("htf_breakdown", pd.DataFrame())

    reliable = phase_session_trend[phase_session_trend["trades"] >= 3] if not phase_session_trend.empty else pd.DataFrame()
    if not reliable.empty:
        worst = reliable.sort_values(["net_R", "trades"], ascending=[True, False]).iloc[0]
        best = reliable.sort_values(["net_R", "trades"], ascending=[False, False]).iloc[0]
        insights.append(
            f"Worst measured HTF context: {worst['combination']} | "
            f"Trades: {int(worst['trades'])} | Winrate: {worst['winrate']:.2f}% | Net R: {worst['net_R']:.2f}"
        )
        insights.append(
            f"Best measured HTF context: {best['combination']} | "
            f"Trades: {int(best['trades'])} | Winrate: {best['winrate']:.2f}% | Net R: {best['net_R']:.2f}"
        )

    if not htf_breakdown.empty:
        neutral = htf_breakdown[htf_breakdown["trend_htf_normalized"] == "neutral"]
        if neutral.empty or int(neutral.iloc[0]["trades"]) < 3:
            insights.append("Neutral HTF has no measurable effect yet because sample size is below 3 trades.")

    if not insights:
        insights.append("HTF impact is not measurable yet with the available fields/sample.")
    insights.append("HTF findings are research evidence only; no automatic rule is applied.")
    return insights


def research_readiness(total_trades: int, reliable_toxic: pd.DataFrame, reliable_positive: pd.DataFrame) -> dict[str, str]:
    if total_trades < 60:
        return {
            "trades_analyzed": str(total_trades),
            "decision_readiness": "LOW",
            "reason": "Sample below 60 trades.",
        }
    if (reliable_toxic is not None and not reliable_toxic.empty) or (
        reliable_positive is not None and not reliable_positive.empty
    ):
        return {
            "trades_analyzed": str(total_trades),
            "decision_readiness": "HIGH",
            "reason": "Sample reached 60+ trades and key clusters exceed minimum confidence threshold.",
        }
    return {
        "trades_analyzed": str(total_trades),
        "decision_readiness": "MEDIUM",
        "reason": "Sample reached 60+ trades, but key clusters need stronger confidence.",
    }


def build_trend_context_analysis(df: pd.DataFrame) -> dict[str, pd.DataFrame | list[str]]:
    work = add_htf_context(df)
    analysis: dict[str, pd.DataFrame | list[str]] = {
        "htf_breakdown": grouped_stats(work, ["trend_htf_normalized"]),
        "phase_trend": grouped_stats(work, ["market_phase", "trend_htf_normalized"]),
        "phase_session_trend": grouped_stats(work, ["market_phase", "session_shadow", "trend_htf_normalized"]),
        "phase_session_setup_trend": grouped_stats(
            work, ["market_phase", "session_shadow", "setup_type", "trend_htf_normalized"]
        ),
        "htf_cluster_analysis": htf_cluster_analysis(work),
        "htf_positive_clusters": htf_positive_clusters(work),
        "alignment_analysis": alignment_analysis(work),
    }
    analysis["htf_impact_report"] = build_htf_impact_report(analysis)
    return analysis
