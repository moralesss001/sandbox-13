from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .hypothesis_registry import ATR_Q33, ATR_Q66, HypothesisRegistry
from .order_models import HypothesisDecisionType, SignalCandidate
from .signal_adapter import signals_from_journal

ORIGINAL_IDS = {"baseline_rr15", "ban_rsi_below_35", "ban_rsi_below_38", "ban_rsi_below_40", "ban_unclear_europe_rebound", "ban_overlap", "ban_unclear_low_rsi", "ban_low_rsi_europe", "ban_rebound_europe", "ban_unclear_europe", "allow_only_mid_rsi", "allow_only_continuation", "allow_us_unknown", "ban_unclear_overlap", "ban_europe_low_rsi"}
SKIPPED_EXISTING = ["allow_only_continuation", "ban_overlap", "ban_rsi_below_40"]
LARGE_CAPS = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "BCHUSDT"}


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(row["r"] > 0 for row in rows)
    losses = sum(row["r"] < 0 for row in rows)
    opened = sum(row["r"] == 0 for row in rows)
    net_r = float(sum(row["r"] for row in rows))
    gross_win = float(sum(row["r"] for row in rows if row["r"] > 0))
    gross_loss = abs(float(sum(row["r"] for row in rows if row["r"] < 0)))
    running = peak = max_drawdown = 0.0
    loss_streak = max_loss_streak = 0
    for row in rows:
        running += row["r"]
        peak = max(peak, running)
        max_drawdown = max(max_drawdown, peak - running)
        if row["r"] < 0:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            loss_streak = 0
    return {"trades": len(rows), "wins": wins, "losses": losses, "open": opened, "winrate": wins / len(rows) * 100 if rows else 0.0, "profit_factor": gross_win / gross_loss if gross_loss else (gross_win if gross_win else 0.0), "expectancy_R": net_r / len(rows) if rows else 0.0, "net_R": net_r, "max_drawdown_R": max_drawdown, "max_loss_streak": max_loss_streak}


def replay_rr15(signal: SignalCandidate, candles: pd.DataFrame) -> dict[str, Any] | None:
    entry_time = pd.to_datetime(signal.raw.get("candle_open_time_utc") or signal.created_at, utc=True, errors="coerce")
    if pd.isna(entry_time):
        return None
    start = candles["timestamp_dt"].searchsorted(entry_time, side="left")
    if start >= len(candles):
        return None
    entry = float(signal.entry)
    risk = abs(entry - float(signal.sl))
    if risk <= 0:
        return None
    direction = signal.direction.upper()
    tp = entry - 1.5 * risk if direction == "SHORT" else entry + 1.5 * risk
    sl = entry + risk if direction == "SHORT" else entry - risk
    result_r = 0.0
    for high, low in candles.loc[start:, ["high", "low"]].itertuples(index=False, name=None):
        high, low = float(high), float(low)
        hit_tp = low <= tp if direction == "SHORT" else high >= tp
        hit_sl = high >= sl if direction == "SHORT" else low <= sl
        if hit_sl:
            result_r = -1.0
            break
        if hit_tp:
            result_r = 1.5
            break
    return {"signal": signal, "r": result_r}


def ranked(items: list[dict[str, Any]], key: str, reverse: bool = True) -> list[dict[str, Any]]:
    return sorted(items, key=lambda row: (row[key], row["trades"]), reverse=reverse)


def duplicates(masks: dict[str, tuple[bool, ...]]) -> list[dict[str, Any]]:
    groups: dict[tuple[bool, ...], list[str]] = defaultdict(list)
    for hypothesis_id, mask in masks.items():
        groups[mask].append(hypothesis_id)
    return [{"hypotheses": ids, "matching_rows": sum(mask), "blocked_rows": len(mask) - sum(mask)} for mask, ids in groups.items() if len(ids) > 1]


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def run(journal: str | Path, candles_path: str | Path, output_md: str | Path, output_json: str | Path) -> dict[str, Any]:
    signals, warnings = signals_from_journal(journal, timeframe="15m")
    candles = pd.read_csv(candles_path)
    candles["timestamp_dt"] = pd.to_datetime(candles["timestamp"], utc=True, errors="coerce")
    by_symbol = {symbol: frame.sort_values("timestamp_dt").reset_index(drop=True) for symbol, frame in candles.groupby("symbol")}
    replay_rows = []
    skip_reasons: dict[str, int] = defaultdict(int)
    for signal in signals:
        frame = by_symbol.get(signal.symbol)
        if frame is None:
            skip_reasons["missing_candles"] += 1
            continue
        replayed = replay_rr15(signal, frame)
        if replayed is None:
            skip_reasons["invalid_or_uncovered_trade"] += 1
            continue
        replay_rows.append(replayed)

    registry = HypothesisRegistry(include_research_pack_2=True)
    all_metrics = []
    masks: dict[str, tuple[bool, ...]] = {}
    for hypothesis in registry.enabled():
        mask = tuple(hypothesis.decide(row["signal"]).decision != HypothesisDecisionType.BLOCK.value for row in replay_rows)
        masks[hypothesis.hypothesis_id] = mask
        accepted = [row for row, allowed in zip(replay_rows, mask) if allowed]
        blocked = [row for row, allowed in zip(replay_rows, mask) if not allowed]
        item = metrics(accepted)
        item.update({"hypothesis_id": hypothesis.hypothesis_id, "rules": hypothesis.rules, "blocked_trades": len(blocked), "blocked_losses": sum(row["r"] < 0 for row in blocked), "missed_wins": sum(row["r"] > 0 for row in blocked), "sample_warning": len(accepted) < 20})
        all_metrics.append(item)

    baseline = next(item for item in all_metrics if item["hypothesis_id"] == "baseline_rr15")
    added = [item.hypothesis_id for item in registry.enabled() if item.hypothesis_id not in ORIGINAL_IDS]
    symbol_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cap_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in replay_rows:
        symbol_groups[row["signal"].symbol].append(row)
        cap_groups["large_caps" if row["signal"].symbol in LARGE_CAPS else "alts"].append(row)
    symbol_leaderboard = []
    for symbol, rows in symbol_groups.items():
        item = metrics(rows)
        item["symbol"] = symbol
        symbol_leaderboard.append(item)
    symbol_leaderboard.sort(key=lambda item: item["net_R"], reverse=True)
    large_caps_vs_alts = []
    for group in ("large_caps", "alts"):
        item = metrics(cap_groups[group])
        item["group"] = group
        large_caps_vs_alts.append(item)

    positive = [item for item in all_metrics if item["expectancy_R"] > 0]
    improved_negative = [item for item in all_metrics if baseline["expectancy_R"] < item["expectancy_R"] <= 0]
    toxic = ranked(all_metrics, "expectancy_R", reverse=False)[:10]
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY" if len(replay_rows) == len(signals) else "PARTIAL",
        "research_only_warning": "Research Pack 2 is old-sample research only; no production decision.",
        "hypotheses_added": added,
        "hypotheses_skipped": [{"hypothesis_id": hid, "reason": "already_present"} for hid in SKIPPED_EXISTING],
        "total_hypothesis_count": len(all_metrics),
        "evaluated_trades": len(replay_rows),
        "skipped_trades": len(signals) - len(replay_rows),
        "skip_reasons": dict(skip_reasons),
        "warnings": warnings,
        "atr_percentile_thresholds": {"q33": ATR_Q33, "q66": ATR_Q66},
        "baseline": baseline,
        "leaderboard_by_expectancy_R": ranked(all_metrics, "expectancy_R"),
        "leaderboard_by_profit_factor": ranked(all_metrics, "profit_factor"),
        "leaderboard_by_net_R": ranked(all_metrics, "net_R"),
        "duplicate_equivalent_masks": duplicates(masks),
        "top_10_toxic_filters": toxic,
        "top_10_positive_candidates": ranked(positive, "expectancy_R")[:10],
        "improved_baseline_but_negative": ranked(improved_negative, "expectancy_R"),
        "positive_but_small_sample": [item for item in positive if item["trades"] < 20],
        "symbol_leaderboard": symbol_leaderboard,
        "large_caps_vs_alts": large_caps_vs_alts,
        "interpretation_safety": {
            "what_improved_old_sample_metrics": [item["hypothesis_id"] for item in ranked(all_metrics, "expectancy_R") if item["expectancy_R"] > baseline["expectancy_R"]],
            "what_stayed_negative": [item["hypothesis_id"] for item in all_metrics if item["expectancy_R"] < 0],
            "what_is_too_small_to_trust": [item["hypothesis_id"] for item in all_metrics if item["trades"] < 20],
            "what_requires_rejected_signals_analysis": ["saved-loss and missed-profit claims for production-rejected signals"],
            "what_requires_live_paper": ["prospective filter behavior without historical-result leakage"],
            "what_requires_new_production_sample": ["stability of all positive and toxic candidates"],
            "what_must_not_be_moved_to_production": ["all Research Pack 2 filters and symbol exclusions"],
        },
    }
    Path(output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def rank_rows(items: list[dict[str, Any]]) -> list[list[Any]]:
        return [[item["hypothesis_id"], item["trades"], f'{item["winrate"]:.2f}%', f'{item["profit_factor"]:.4f}', f'{item["expectancy_R"]:.4f}', f'{item["net_R"]:.2f}', "YES" if item["sample_warning"] else ""] for item in items]

    md = [
        "# Research Pack 2 Report", "", f'**Status:** {payload["status"]}', "",
        f'- hypotheses added: {len(added)}', f'- hypotheses skipped: {len(SKIPPED_EXISTING)} (already present)',
        f'- total hypotheses: {len(all_metrics)}', f'- evaluated/skipped trades: {len(replay_rows)}/{len(signals)-len(replay_rows)}',
        f'- ATR q33/q66: {ATR_Q33:.10f} / {ATR_Q66:.10f}', "- warning: research-only; no production decision.", "",
        "## Hypotheses Added", "", ", ".join(added), "", "## Hypotheses Skipped", "",
        *[f'- {hid}: already present' for hid in SKIPPED_EXISTING], "",
        "## Leaderboard By Expectancy R", "", table(["hypothesis","trades","winrate","PF","expectancy_R","net_R","<20 warning"], rank_rows(payload["leaderboard_by_expectancy_R"])), "",
        "## Leaderboard By Profit Factor", "", table(["hypothesis","trades","winrate","PF","expectancy_R","net_R","<20 warning"], rank_rows(payload["leaderboard_by_profit_factor"])), "",
        "## Leaderboard By Net R", "", table(["hypothesis","trades","winrate","PF","expectancy_R","net_R","<20 warning"], rank_rows(payload["leaderboard_by_net_R"])), "",
        "## Duplicate / Equivalent Masks", "", table(["hypotheses","matching rows","blocked rows"], [[" = ".join(item["hypotheses"]), item["matching_rows"], item["blocked_rows"]] for item in payload["duplicate_equivalent_masks"]]), "",
        "## Top 10 Toxic Filters", "", table(["hypothesis","trades","winrate","PF","expectancy_R","net_R","<20 warning"], rank_rows(toxic)), "",
        "## Top 10 Positive Candidates", "", table(["hypothesis","trades","winrate","PF","expectancy_R","net_R","<20 warning"], rank_rows(payload["top_10_positive_candidates"])), "",
        "## Improved Baseline But Remain Negative", "", table(["hypothesis","trades","winrate","PF","expectancy_R","net_R","<20 warning"], rank_rows(payload["improved_baseline_but_negative"])), "",
        "## Positive But Too Small To Trust", "", table(["hypothesis","trades","winrate","PF","expectancy_R","net_R","<20 warning"], rank_rows(payload["positive_but_small_sample"])), "",
        "## Symbol Leaderboard", "", table(["symbol","trades","winrate","PF","expectancy_R","net_R"], [[x["symbol"],x["trades"],f'{x["winrate"]:.2f}%',f'{x["profit_factor"]:.4f}',f'{x["expectancy_R"]:.4f}',f'{x["net_R"]:.2f}'] for x in symbol_leaderboard]), "",
        "## Large Caps Vs Alts", "", table(["group","trades","winrate","PF","expectancy_R","net_R"], [[x["group"],x["trades"],f'{x["winrate"]:.2f}%',f'{x["profit_factor"]:.4f}',f'{x["expectancy_R"]:.4f}',f'{x["net_R"]:.2f}'] for x in large_caps_vs_alts]), "",
        "## Interpretation Safety", "", "- Improvements are historical old-sample observations only.", "- Negative candidates remain negative and are not production-ready.", "- Any hypothesis with fewer than 20 trades is explicitly marked.", "- Rejected-signal conclusions require rejected_signals outcomes.", "- Prospective validity requires live paper.", "- Stability requires a new production sample.", "- Nothing in Research Pack 2 may be moved to production yet.", "",
        "## Safety", "", "- Production Crypto13 was not touched.", "- Binance API/live paper was not started.", "- No real or testnet orders were added or sent.",
    ]
    Path(output_md).write_text("\n".join(md), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", required=True)
    parser.add_argument("--candles", required=True)
    parser.add_argument("--out-md", default="reports/RESEARCH_PACK_2_REPORT.md")
    parser.add_argument("--out-json", default="reports/RESEARCH_PACK_2_REPORT.json")
    args = parser.parse_args()
    payload = run(args.journal, args.candles, args.out_md, args.out_json)
    print(json.dumps({"status": payload["status"], "added": len(payload["hypotheses_added"]), "skipped": len(payload["hypotheses_skipped"]), "total": payload["total_hypothesis_count"], "evaluated": payload["evaluated_trades"], "skipped_trades": payload["skipped_trades"]}, indent=2))


if __name__ == "__main__":
    main()
