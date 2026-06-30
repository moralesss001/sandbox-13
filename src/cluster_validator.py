from __future__ import annotations

import json
from datetime import datetime
from math import sqrt
from pathlib import Path
from typing import Any

import pandas as pd

CONFIDENCE_ORDER = {"VERY_LOW": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
DEFAULT_HISTORY_PATH = Path("data/cluster_history/cluster_tracker.json")


def confidence_for_trades(trades: int) -> str:
    if trades < 3:
        return "VERY_LOW"
    if trades < 5:
        return "LOW"
    if trades < 10:
        return "MEDIUM"
    return "HIGH"


def validate_clusters(cluster_stats: pd.DataFrame, global_expectancy: float) -> pd.DataFrame:
    columns = [
        "combination",
        "trades",
        "wins",
        "losses",
        "winrate",
        "avg_R",
        "expectancy",
        "net_R",
        "confidence_score",
        "stability_score",
    ]
    if cluster_stats is None or cluster_stats.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for _, row in cluster_stats.iterrows():
        trades = int(row.get("trades", 0))
        expectancy = float(row.get("expectancy", row.get("avg_R", 0.0)) or 0.0)
        stability_score = abs(expectancy - global_expectancy) * sqrt(trades) if trades else 0.0
        rows.append(
            {
                "combination": row.get("combination", "UNKNOWN"),
                "trades": trades,
                "wins": int(row.get("wins", 0)),
                "losses": int(row.get("losses", 0)),
                "winrate": float(row.get("winrate", 0.0) or 0.0),
                "avg_R": float(row.get("avg_R", 0.0) or 0.0),
                "expectancy": expectancy,
                "net_R": float(row.get("net_R", 0.0) or 0.0),
                "confidence_score": confidence_for_trades(trades),
                "stability_score": float(stability_score),
            }
        )

    validated = pd.DataFrame(rows)
    return validated.sort_values(["stability_score", "trades"], ascending=[False, False]).reset_index(drop=True)


def _at_least_medium(value: str) -> bool:
    return CONFIDENCE_ORDER.get(value, 0) >= CONFIDENCE_ORDER["MEDIUM"]


def most_reliable_toxic_clusters(validated: pd.DataFrame) -> pd.DataFrame:
    if validated is None or validated.empty:
        return pd.DataFrame(columns=["combination", "trades", "winrate", "net_R", "confidence_score", "stability_score"])
    reliable = validated[
        validated["confidence_score"].map(_at_least_medium)
        & ((validated["winrate"] < 35) | (validated["net_R"] < -2))
    ]
    return reliable.sort_values(["net_R", "stability_score"], ascending=[True, False]).reset_index(drop=True)


def most_reliable_positive_clusters(validated: pd.DataFrame) -> pd.DataFrame:
    if validated is None or validated.empty:
        return pd.DataFrame(columns=["combination", "trades", "winrate", "net_R", "confidence_score", "stability_score"])
    reliable = validated[
        validated["confidence_score"].map(_at_least_medium)
        & ((validated["winrate"] > 65) | (validated["net_R"] > 2))
    ]
    return reliable.sort_values(["net_R", "stability_score"], ascending=[False, False]).reset_index(drop=True)


def _snapshot_rows(validated: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if validated is None or validated.empty:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for _, row in validated.iterrows():
        combination = str(row["combination"])
        rows[combination] = {
            "trades": int(row["trades"]),
            "wins": int(row["wins"]),
            "losses": int(row["losses"]),
            "winrate": float(row["winrate"]),
            "avg_R": float(row["avg_R"]),
            "expectancy": float(row["expectancy"]),
            "net_R": float(row["net_R"]),
            "confidence_score": str(row["confidence_score"]),
            "stability_score": float(row["stability_score"]),
        }
    return rows


def load_cluster_history(path: str | Path = DEFAULT_HISTORY_PATH) -> dict[str, Any]:
    history_path = Path(path)
    if not history_path.exists():
        return {"snapshots": []}
    try:
        with history_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {"snapshots": []}
    if not isinstance(data, dict) or not isinstance(data.get("snapshots"), list):
        return {"snapshots": []}
    return data


def save_cluster_snapshot(
    validated: pd.DataFrame,
    source_file: str | Path | None = None,
    path: str | Path = DEFAULT_HISTORY_PATH,
) -> dict[str, Any]:
    history_path = Path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history = load_cluster_history(history_path)
    snapshot = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(source_file) if source_file is not None else None,
        "clusters": _snapshot_rows(validated),
    }
    history["snapshots"].append(snapshot)
    history["latest"] = snapshot
    with history_path.open("w", encoding="utf-8") as fh:
        json.dump(history, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return snapshot


def compare_cluster_versions(previous: dict[str, Any] | None, current: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "combination",
        "previous_trades",
        "current_trades",
        "previous_winrate",
        "current_winrate",
        "previous_net_R",
        "current_net_R",
        "trend",
    ]
    if previous is None or not previous.get("clusters"):
        return pd.DataFrame(columns=columns)

    previous_clusters = previous.get("clusters", {})
    current_rows = _snapshot_rows(current)
    combinations = sorted(set(previous_clusters) | set(current_rows))
    rows = []
    for combination in combinations:
        prev = previous_clusters.get(combination, {})
        curr = current_rows.get(combination, {})
        previous_net = float(prev.get("net_R", 0.0))
        current_net = float(curr.get("net_R", 0.0))
        delta = current_net - previous_net
        if delta > 0.5:
            trend = "Improving"
        elif delta < -0.5:
            trend = "Degrading"
        else:
            trend = "Stable"
        rows.append(
            {
                "combination": combination,
                "previous_trades": int(prev.get("trades", 0)),
                "current_trades": int(curr.get("trades", 0)),
                "previous_winrate": float(prev.get("winrate", 0.0)),
                "current_winrate": float(curr.get("winrate", 0.0)),
                "previous_net_R": previous_net,
                "current_net_R": current_net,
                "trend": trend,
            }
        )
    return pd.DataFrame(rows).sort_values(["trend", "current_net_R"]).reset_index(drop=True)
