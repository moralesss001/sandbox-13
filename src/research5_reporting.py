from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd


BLOCK_ATTRIBUTION_IDS = (
    "block_rsi_below_35_only",
    "block_rsi_above_65_only",
    "block_bearish_pattern_only",
    "block_sl_width_only",
    "block_multiple_reasons",
)


def research_005_report_sections(
    portfolios: dict[str, Any],
    metrics: dict[str, dict[str, Any]],
) -> str:
    baseline = portfolios.get("baseline_rr15")
    trades = list(getattr(baseline, "closed_trades", []) or [])
    sections = [
        "## Research #005 Market Profile",
        _breakdown_table(trades, ("market_profile_v1",)),
        "",
        "## Profile confidence",
        _breakdown_table(trades, ("market_profile_confidence",)),
        "",
        "## RSI zone",
        _breakdown_table(trades, ("rsi_zone",)),
        "",
        "## Interaction hypotheses",
        _hypothesis_table(metrics),
        "",
        "## Production block attribution",
        _hypothesis_table({key: metrics[key] for key in BLOCK_ATTRIBUTION_IDS if key in metrics}),
        "",
        "## Session x Market Profile",
        _breakdown_table(trades, ("session", "market_profile_v1")),
        "",
        "## Market phase x Market Profile",
        _breakdown_table(trades, ("market_phase", "market_profile_v1")),
        "",
        "## Symbol concentration (baseline)",
        _symbol_concentration(trades),
        "",
        "_Research-only analytics. No automatic production conclusions._",
    ]
    return "\n".join(sections)


def _breakdown_table(trades: list[Any], fields: tuple[str, ...]) -> str:
    groups: dict[tuple[str, ...], list[Any]] = defaultdict(list)
    for trade in trades:
        key = tuple(str(getattr(trade, field, None) or "UNKNOWN") for field in fields)
        groups[key].append(trade)
    rows = []
    for key, items in sorted(groups.items()):
        row = {field: value for field, value in zip(fields, key)}
        row.update(_trade_metrics(items))
        rows.append(row)
    return _markdown_rows(rows) if rows else "_No closed baseline trades._"


def _trade_metrics(trades: list[Any]) -> dict[str, Any]:
    values = [float(getattr(trade, "r", 0.0) or 0.0) for trade in trades]
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = abs(sum(value for value in values if value < 0))
    net_r = sum(values)
    total = len(values)
    return {
        "N": total,
        "wins": wins,
        "losses": losses,
        "WR": round(wins / total * 100.0, 2) if total else 0.0,
        "net_R": round(net_r, 6),
        "gross_profit_R": round(gross_profit, 6),
        "gross_loss_R": round(gross_loss, 6),
        "expectancy_R": round(net_r / total, 6) if total else 0.0,
        "profit_factor": _profit_factor(gross_profit, gross_loss),
    }


def _hypothesis_table(metrics: dict[str, dict[str, Any]]) -> str:
    rows = []
    for hypothesis_id, item in metrics.items():
        gross_profit = float(item.get("gross_profit_R", 0.0) or 0.0)
        gross_loss = float(item.get("gross_loss_R", 0.0) or 0.0)
        rows.append(
            {
                "hypothesis_id": hypothesis_id,
                "N": int(item.get("total_trades", 0) or 0),
                "wins": int(item.get("wins", 0) or 0),
                "losses": int(item.get("losses", 0) or 0),
                "WR": round(float(item.get("winrate", 0.0) or 0.0), 2),
                "net_R": round(float(item.get("net_R", 0.0) or 0.0), 6),
                "gross_profit_R": round(gross_profit, 6),
                "gross_loss_R": round(gross_loss, 6),
                "expectancy_R": round(float(item.get("expectancy", 0.0) or 0.0), 6),
                "profit_factor": _profit_factor(gross_profit, gross_loss),
            }
        )
    return _markdown_rows(rows) if rows else "_No metrics._"


def _profit_factor(gross_profit: float, gross_loss: float) -> float | None:
    if gross_loss == 0:
        return None
    return round(gross_profit / gross_loss, 6)


def _markdown_rows(rows: list[dict[str, Any]]) -> str:
    frame = pd.DataFrame(rows).astype(object)
    frame = frame.where(pd.notna(frame), "N/A")
    return frame.to_markdown(index=False)


def _symbol_concentration(trades: list[Any]) -> str:
    grouped: dict[str, float] = defaultdict(float)
    for trade in trades:
        grouped[str(getattr(trade, "symbol", None) or "UNKNOWN")] += float(
            getattr(trade, "r", 0.0) or 0.0
        )
    positive_total = sum(value for value in grouped.values() if value > 0)
    rows = [
        {
            "symbol": symbol,
            "R": round(value, 6),
            "share_positive_R_pct": round(value / positive_total * 100.0, 2)
            if value > 0 and positive_total
            else 0.0,
        }
        for symbol, value in sorted(grouped.items(), key=lambda item: item[1], reverse=True)[:5]
    ]
    return _markdown_rows(rows) if rows else "_No closed baseline trades._"
