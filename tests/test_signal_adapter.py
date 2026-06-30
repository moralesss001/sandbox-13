from pathlib import Path

from src.signal_adapter import signals_from_journal


def test_journal_signal_adapter_preserves_signal_source(tmp_path: Path):
    csv_path = tmp_path / "signals.csv"
    csv_path.write_text(
        "\n".join(
            [
                "timeframe,result,symbol,direction,entry,tp,sl,rsi,atr_pct,session_msk,market_phase,setup_type,trend_htf,rr_ratio",
                "15m,TP,BTCUSDT,LONG,100,115,90,44,0.01,EUROPE,unclear,rebound,Short,1.5",
            ]
        ),
        encoding="utf-8",
    )

    signals, warnings = signals_from_journal(csv_path, timeframe="15m")

    assert warnings == []
    assert len(signals) == 1
    assert signals[0].signal_source == "journal_replay"
    assert signals[0].session == "EUROPE"


def test_journal_signal_adapter_normalizes_eu_us(tmp_path: Path):
    csv_path = tmp_path / "signals.csv"
    csv_path.write_text(
        "timeframe,result,symbol,direction,entry,tp,sl,session_msk\n"
        "15m,SL,BTCUSDT,LONG,100,115,90,EU_US\n",
        encoding="utf-8",
    )

    signals, _ = signals_from_journal(csv_path)

    assert signals[0].session == "OVERLAP"
