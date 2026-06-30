import pandas as pd

from src.metrics import baseline_metrics, shadow_effect


def test_baseline_metrics():
    df = pd.DataFrame(
        {
            "result_normalized": ["win", "loss", "win"],
            "r": [1.5, -1.0, 1.5],
        }
    )

    metrics = baseline_metrics(df)

    assert metrics["total_trades"] == 3
    assert metrics["wins"] == 2
    assert metrics["losses"] == 1
    assert metrics["gross_win_R"] == 3.0
    assert metrics["gross_loss_R"] == 1.0
    assert metrics["profit_factor"] == 3.0


def test_shadow_effect():
    df = pd.DataFrame(
        {
            "result_normalized": ["win", "loss", "loss", "win"],
            "decision_shadow": ["NO_TRADE", "NO_TRADE", "ALLOW", "ALLOW"],
            "r": [1.5, -1.0, -1.0, 1.5],
        }
    )

    effect = shadow_effect(df)

    assert effect["blocked_losses_count"] == 1
    assert effect["blocked_losses_R"] == 1.0
    assert effect["missed_wins_count"] == 1
    assert effect["missed_wins_R"] == 1.5
    assert effect["net_effect_R"] == -0.5
