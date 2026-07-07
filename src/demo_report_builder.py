from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .gate_analytics import summarize_gate_outcomes


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _metrics_table(metrics: dict[str, dict[str, Any]]) -> str:
    rows = []
    for hypothesis_id, item in metrics.items():
        row = {"hypothesis_id": hypothesis_id}
        row.update(item)
        rows.append(row)
    if not rows:
        return "_No metrics._"
    columns = [
        "hypothesis_id",
        "total_trades",
        "wins",
        "losses",
        "winrate",
        "profit_factor",
        "expectancy",
        "net_R",
        "max_drawdown_R",
        "trades_blocked",
        "blocked_losses",
        "missed_wins",
        "candidate_for_testnet",
    ]
    return pd.DataFrame(rows)[columns].sort_values("net_R", ascending=False).to_markdown(index=False)


def build_demo_report(
    result: dict[str, Any],
    out_dir: str | Path = "data/demo_reports",
    source_file: str | Path | None = None,
    signal_source: str = "unknown",
) -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    report_path = out_path / f"demo_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    metrics = result.get("metrics", {})
    baseline = metrics.get("baseline_rr15", {})
    leaderboard = sorted(metrics.values(), key=lambda item: item.get("net_R", 0.0), reverse=True)
    best_net = leaderboard[0] if leaderboard else {}
    best_pf = max(metrics.values(), key=lambda item: item.get("profit_factor", 0.0), default={})
    best_dd = min(metrics.values(), key=lambda item: item.get("max_drawdown_R", 0.0), default={})
    worst = min(metrics.values(), key=lambda item: item.get("net_R", 0.0), default={})
    candidates = [item for item in metrics.values() if item.get("candidate_for_testnet")]
    low_sample = [item for item in metrics.values() if item.get("total_trades", 0) < 30]
    rejected = [item for item in metrics.values() if not item.get("candidate_for_testnet")]
    candidate_source = result.get("candidate_source", "unknown")
    candidate_source_version = result.get("candidate_source_version", "unknown")
    candidate_source_warning = result.get("candidate_source_warning") or ""
    edge_conclusions_allowed = result.get("edge_conclusions_allowed", "unknown")
    live_direction_policy = result.get("live_direction_policy", "unknown")
    closed_trades = []
    for portfolio in result.get("portfolios", {}).values():
        closed_trades.extend(getattr(portfolio, "closed_trades", []))
    gate_outcomes = result.get("gate_outcome_analytics") or summarize_gate_outcomes(closed_trades)

    lines = [
        "# Crypto13Research Demo Report",
        "",
        "## 1. Summary",
        f"- Source file: `{source_file or 'n/a'}`",
        f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"- Hypotheses evaluated: {len(metrics)}",
        "",
        "## 2. Signal source",
        f"`signal_source = {signal_source}`",
        f"`candidate_source = {candidate_source}`",
        f"`candidate_source_version = {candidate_source_version}`",
        f"`edge_conclusions_allowed = {edge_conclusions_allowed}`",
        f"`live_direction_policy = {live_direction_policy}`",
        f"- Candidate source warning: {candidate_source_warning or 'n/a'}",
        "",
        "## 3. Shadow gate analytics",
        f"- gate_saved_from_loss: {_fmt(gate_outcomes.get('gate_saved_from_loss', 0))}",
        f"- gate_missed_profit: {_fmt(gate_outcomes.get('gate_missed_profit', 0))}",
        f"- gate_allowed_loss: {_fmt(gate_outcomes.get('gate_allowed_loss', 0))}",
        f"- gate_allowed_profit: {_fmt(gate_outcomes.get('gate_allowed_profit', 0))}",
        "- Shadow gates are analytics-only in sandbox and are not hard filters.",
        "",
        "## 4. Baseline metrics",
        "\n".join(f"- {key}: {_fmt(value)}" for key, value in baseline.items()) if baseline else "_No baseline._",
        "",
        "## 5. Hypothesis leaderboard",
        _metrics_table(metrics),
        "",
        "## 6. Baseline vs filters",
        f"- Baseline net_R: {_fmt(baseline.get('net_R'))}",
        f"- Best filter net_R: {_fmt(best_net.get('net_R'))}",
        "",
        "## 7. Best hypothesis by net_R",
        f"`{best_net.get('hypothesis_id', 'n/a')}` net_R={_fmt(best_net.get('net_R'))}",
        "",
        "## 8. Best hypothesis by PF",
        f"`{best_pf.get('hypothesis_id', 'n/a')}` PF={_fmt(best_pf.get('profit_factor'))}",
        "",
        "## 9. Best hypothesis by max_drawdown",
        f"`{best_dd.get('hypothesis_id', 'n/a')}` max_drawdown_R={_fmt(best_dd.get('max_drawdown_R'))}",
        "",
        "## 10. Worst hypothesis",
        f"`{worst.get('hypothesis_id', 'n/a')}` net_R={_fmt(worst.get('net_R'))}",
        "",
        "## 11. Trades per hypothesis",
        "\n".join(f"- {hid}: {m.get('total_trades', 0)}" for hid, m in metrics.items()),
        "",
        "## 12. Blocked trades per hypothesis",
        "\n".join(f"- {hid}: {m.get('trades_blocked', 0)}" for hid, m in metrics.items()),
        "",
        "## 13. Missed wins",
        "\n".join(f"- {hid}: {m.get('missed_wins', 0)}" for hid, m in metrics.items()),
        "",
        "## 14. Saved losses",
        "\n".join(f"- {hid}: {m.get('blocked_losses', 0)}" for hid, m in metrics.items()),
        "",
        "## 15. Portfolio equity summary",
        "\n".join(
            f"- {hid}: balance={_fmt(portfolio.balance)} net_R={_fmt(portfolio.net_R)}"
            for hid, portfolio in result.get("portfolios", {}).items()
        ),
        "",
        "## 16. Hypotheses that need more data",
        "\n".join(f"- {item.get('hypothesis_id')}: trades={item.get('total_trades')}" for item in low_sample)
        or "- none",
        "",
        "## 17. Hypotheses rejected",
        "\n".join(f"- {item.get('hypothesis_id')}" for item in rejected) or "- none",
        "",
        "## 18. Candidates for testnet execution",
        "\n".join(f"- {item.get('hypothesis_id')}" for item in candidates) or "- none",
        "",
        "## 19. Safety status",
        "- API_MODE default: paper",
        "- ALLOW_REAL_ORDERS: false",
        "- Testnet orders require allow flag and explicit CLI confirmation.",
        "- Production trading is disabled in Crypto13Research.",
        "",
        "## 20. What NOT to deploy yet",
        "- Do not deploy any hypothesis to production from this report.",
        "- Do not treat paper/testnet candidates as production proof.",
        "- Send all production decisions back to Crypto13 HQ.",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
