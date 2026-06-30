import pandas as pd

from src.cluster_validator import (
    compare_cluster_versions,
    confidence_for_trades,
    load_cluster_history,
    most_reliable_positive_clusters,
    most_reliable_toxic_clusters,
    save_cluster_snapshot,
    validate_clusters,
)


def _stats():
    return pd.DataFrame(
        {
            "combination": ["unclear + US + rebound", "range + EUROPE + unknown", "tiny + sample + only"],
            "trades": [12, 6, 3],
            "wins": [3, 5, 2],
            "losses": [9, 1, 1],
            "winrate": [25.0, 83.33, 66.67],
            "avg_R": [-0.5, 0.67, 0.33],
            "expectancy": [-0.5, 0.67, 0.33],
            "net_R": [-6.0, 4.0, 1.0],
        }
    )


def test_confidence_for_trades():
    assert confidence_for_trades(2) == "VERY_LOW"
    assert confidence_for_trades(3) == "LOW"
    assert confidence_for_trades(4) == "LOW"
    assert confidence_for_trades(5) == "MEDIUM"
    assert confidence_for_trades(9) == "MEDIUM"
    assert confidence_for_trades(10) == "HIGH"


def test_validate_clusters_adds_confidence_and_stability():
    validated = validate_clusters(_stats(), global_expectancy=0.0)
    toxic = validated[validated["combination"] == "unclear + US + rebound"].iloc[0]

    assert toxic["confidence_score"] == "HIGH"
    assert toxic["stability_score"] > 0


def test_reliable_clusters_require_medium_or_high_confidence():
    validated = validate_clusters(_stats(), global_expectancy=0.0)

    toxic = most_reliable_toxic_clusters(validated)
    positive = most_reliable_positive_clusters(validated)

    assert list(toxic["combination"]) == ["unclear + US + rebound"]
    assert list(positive["combination"]) == ["range + EUROPE + unknown"]


def test_cluster_history_save_load_and_compare(tmp_path):
    history_path = tmp_path / "cluster_tracker.json"
    first = validate_clusters(_stats(), global_expectancy=0.0)
    save_cluster_snapshot(first, source_file="first.csv", path=history_path)
    history = load_cluster_history(history_path)

    second_stats = _stats()
    second_stats.loc[0, "net_R"] = -9.0
    second_stats.loc[0, "trades"] = 18
    second = validate_clusters(second_stats, global_expectancy=0.0)
    evolution = compare_cluster_versions(history["latest"], second)
    toxic_row = evolution[evolution["combination"] == "unclear + US + rebound"].iloc[0]

    assert toxic_row["previous_trades"] == 12
    assert toxic_row["current_trades"] == 18
    assert toxic_row["trend"] == "Degrading"
