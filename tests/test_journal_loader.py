from pathlib import Path

from src.journal_loader import load_journal_csv, normalize_result


def test_normalize_result():
    assert normalize_result("TP") == "win"
    assert normalize_result("take_profit") == "win"
    assert normalize_result("SL") == "loss"
    assert normalize_result("stop_loss") == "loss"


def test_load_journal_filters_timeframe_and_calculates_r(tmp_path: Path):
    csv_path = tmp_path / "signals.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Time Frame,result,entry,tp,sl,rsi,atr_pct",
                "15m,TP,100,115,90,50,0.5",
                "1h,SL,100,115,90,50,0.5",
                "15m,SL,100,115,90,50,0.5",
            ]
        ),
        encoding="utf-8",
    )

    df, warnings = load_journal_csv(csv_path, timeframe="15m")

    assert len(df) == 2
    assert warnings == []
    assert list(df["result_normalized"]) == ["win", "loss"]
    assert list(df["r"]) == [1.5, -1.0]
