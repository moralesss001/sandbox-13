from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .combination_analyzer import build_combination_analysis, build_combination_insights
from .cluster_validator import (
    DEFAULT_HISTORY_PATH,
    compare_cluster_versions,
    load_cluster_history,
    most_reliable_positive_clusters,
    most_reliable_toxic_clusters,
    save_cluster_snapshot,
    validate_clusters,
)
from .metrics import calculate_metrics
from .trend_context_analyzer import build_trend_context_analysis, research_readiness


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _dict_table(data: dict[str, Any]) -> str:
    lines = ["| Metric | Value |", "|---|---:|"]
    for key, value in data.items():
        lines.append(f"| {key} | {_fmt(value)} |")
    return "\n".join(lines)


def _df_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df is None or df.empty:
        return "_No data._"
    return df.head(max_rows).to_markdown(index=False)


def _sample_table(df: pd.DataFrame, mask: pd.Series, max_rows: int = 20) -> str:
    cols = [
        col
        for col in [
            "signal_id",
            "symbol",
            "timeframe",
            "direction",
            "result_normalized",
            "r",
            "market_phase",
            "session_shadow",
            "setup_type",
            "strategy_mode_shadow",
            "risk_mode_shadow",
            "decision_shadow",
        ]
        if col in df.columns
    ]
    sample = df[mask][cols].head(max_rows)
    return _df_table(sample)


def build_report(
    replay_df: pd.DataFrame,
    warnings: list[str],
    out_dir: str | Path = "data/reports",
    source_file: str | Path | None = None,
) -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    report_path = out_path / f"replay_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    metrics = calculate_metrics(replay_df)
    combination_analysis = build_combination_analysis(replay_df)
    combination_insights = build_combination_insights(combination_analysis)
    baseline = metrics["baseline"]
    effect = metrics["shadow_effect"]
    breakdowns = metrics["breakdowns"]
    cluster_confidence = validate_clusters(combination_analysis["phase_session_setup"], baseline["expectancy"])
    reliable_toxic = most_reliable_toxic_clusters(cluster_confidence)
    reliable_positive = most_reliable_positive_clusters(cluster_confidence)
    trend_analysis = build_trend_context_analysis(replay_df)
    history = load_cluster_history(DEFAULT_HISTORY_PATH)
    previous_snapshot = history["snapshots"][-1] if history.get("snapshots") else None
    cluster_evolution = compare_cluster_versions(previous_snapshot, cluster_confidence)
    save_cluster_snapshot(cluster_confidence, source_file=source_file, path=DEFAULT_HISTORY_PATH)

    total = baseline["total_trades"]
    readiness = research_readiness(total, reliable_toxic, reliable_positive)
    small_sample_lines = []
    if total < 30:
        small_sample_lines.append("WARNING: sample has fewer than 30 closed trades; conclusions are very fragile.")
    if total < 60:
        small_sample_lines.append("Sample has fewer than 60 closed trades; treat results as preliminary.")
    if not small_sample_lines:
        small_sample_lines.append("Sample size reached the initial 60-trade target.")

    blocked_losses_mask = (replay_df.get("decision_shadow") == "NO_TRADE") & (
        replay_df.get("result_normalized") == "loss"
    )
    missed_wins_mask = (replay_df.get("decision_shadow") == "NO_TRADE") & (
        replay_df.get("result_normalized") == "win"
    )

    columns_found = replay_df.attrs.get("normalized_columns") or list(replay_df.columns)
    expected_columns = {
        "timeframe",
        "result",
        "entry",
        "tp",
        "sl",
        "rsi",
        "atr_pct",
        "market_phase",
        "setup_type",
        "trend_htf",
        "impulse_before_entry",
        "reason",
        "confidence_factors",
        "rr_ratio",
        "session_msk",
        "hour_msk",
    }
    missing_columns = sorted(expected_columns - set(columns_found))

    lines = [
        "# Crypto13 Research Replay Report",
        "",
        "## 1. Summary",
        f"- Source file: `{source_file or 'n/a'}`",
        f"- Closed trades analyzed: {total}",
        f"- Shadow net effect: {_fmt(effect['net_effect_R'])} R",
        f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 2. Baseline metrics",
        _dict_table(baseline),
        "",
        "## 3. Shadow architecture metrics",
        _dict_table(effect),
        "",
        "## 4. Blocked losses",
        _sample_table(replay_df, blocked_losses_mask),
        "",
        "## 5. Missed wins",
        _sample_table(replay_df, missed_wins_mask),
        "",
        "## 6. Net R effect",
        f"`blocked_losses_R - missed_wins_R = {_fmt(effect['net_effect_R'])} R`",
        "",
        "## 7. Breakdown by market_phase",
        _df_table(breakdowns["market_phase"]),
        "",
        "## 8. Breakdown by session",
        _df_table(breakdowns["session_shadow"]),
        "",
        "## 9. Breakdown by setup_type",
        _df_table(breakdowns["setup_type"]),
        "",
        "## 10. Breakdown by rsi_zone",
        _df_table(breakdowns["rsi_zone"]),
        "",
        "## 11. Breakdown by volatility_state",
        _df_table(breakdowns["volatility_state"]),
        "",
        "## 12. Breakdown by strategy_mode_shadow",
        _df_table(breakdowns["strategy_mode_shadow"]),
        "",
        "## 13. Breakdown by decision_shadow",
        _df_table(breakdowns["decision_shadow"]),
        "",
        "## 14. Top toxic combinations",
        _df_table(metrics["top_toxic_combinations"]),
        "",
        "## 15. Combination level 2: market_phase + session",
        _df_table(combination_analysis["phase_session"]),
        "",
        "## 16. Combination level 3: market_phase + session + setup_type",
        _df_table(combination_analysis["phase_session_setup"]),
        "",
        "## 17. RSI combinations: market_phase + rsi_zone",
        _df_table(combination_analysis["phase_rsi"]),
        "",
        "## 18. RSI combinations: market_phase + session + rsi_zone",
        _df_table(combination_analysis["phase_session_rsi"]),
        "",
        "## 19. RR breakdown",
        _df_table(combination_analysis["rr_ratio"]),
        "",
        "## 20. Toxic combinations",
        _df_table(combination_analysis["toxic_combinations"]),
        "",
        "## 21. Positive combinations",
        _df_table(combination_analysis["positive_combinations"]),
        "",
        "## 22. Combination Insights",
        "\n".join(f"- {insight}" for insight in combination_insights),
        "",
        "## 23. Cluster Confidence",
        _df_table(cluster_confidence),
        "",
        "## 24. Most Reliable Toxic Clusters",
        _df_table(reliable_toxic),
        "",
        "## 25. Most Reliable Positive Clusters",
        _df_table(reliable_positive),
        "",
        "## 26. Cluster Evolution",
        _df_table(cluster_evolution),
        "",
        "## 27. HTF Trend Breakdown",
        _df_table(trend_analysis["htf_breakdown"]),
        "",
        "## 28. HTF market_phase + trend_htf",
        _df_table(trend_analysis["phase_trend"]),
        "",
        "## 29. HTF market_phase + session + trend_htf",
        _df_table(trend_analysis["phase_session_trend"]),
        "",
        "## 30. HTF market_phase + session + setup_type + trend_htf",
        _df_table(trend_analysis["phase_session_setup_trend"]),
        "",
        "## 31. HTF Cluster Analysis",
        _df_table(trend_analysis["htf_cluster_analysis"]),
        "",
        "## 32. HTF Positive Clusters",
        _df_table(trend_analysis["htf_positive_clusters"]),
        "",
        "## 33. HTF Impact Report",
        "\n".join(f"- {insight}" for insight in trend_analysis["htf_impact_report"]),
        "",
        "## 34. Alignment Analysis",
        _df_table(trend_analysis["alignment_analysis"]),
        "",
        "## 35. Research Readiness",
        _dict_table(readiness),
        "",
        "## 36. What architecture would have blocked",
        _sample_table(replay_df, replay_df.get("decision_shadow") == "NO_TRADE"),
        "",
        "## 37. What architecture would have missed",
        _sample_table(replay_df, missed_wins_mask),
        "",
        "## 38. Warnings about small sample size",
        "\n".join(f"- {line}" for line in small_sample_lines),
        *(["- " + warning for warning in warnings] if warnings else ["- No loader/context warnings."]),
        "",
        "## 39. Hypotheses for next test",
        "- Check whether toxic combinations remain toxic after the 60-trade RR 1.5 sample is complete.",
        "- Compare NO_TRADE blocks against market_phase/session/setup_type before changing production logic.",
        "- Validate whether HIGH_VOL should reduce risk or fully block only in specific sessions.",
        "- Use combination analysis to identify where unclear market contains both high-quality and toxic clusters.",
        "- Treat LOW confidence clusters as weak evidence until more trades accumulate.",
        "",
        "## 40. What NOT to change yet",
        "- Do not change the production Crypto13 strategy based on this sandbox run alone.",
        "- Do not change the active RR 1.5 test until the clean sample is complete and reviewed.",
        "- Do not add trading API keys or order execution to this research project.",
        "- Do not automatically ban a combination from this report; it is evidence for human review.",
        "- Stop adding new analyzers until the next RR 1.5 sample is collected and reviewed.",
        "",
        "## CSV schema observed",
        f"- Columns found: `{', '.join(map(str, columns_found))}`",
        f"- Expected columns missing: `{', '.join(missing_columns) if missing_columns else 'none'}`",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
