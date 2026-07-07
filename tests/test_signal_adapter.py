from pathlib import Path

import pandas as pd

from src.candidate_sources import DirectionSupport
from src.signal_adapter import signal_from_klines
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
    assert signals[0].candidate_source == "production_baseline_export"
    assert signals[0].candidate_source_version == "legacy_journal_v1"
    assert signals[0].edge_conclusions_allowed is True
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


def test_simplified_placeholder_klines_signal_has_source_metadata():
    rows = []
    for index in range(20):
        close = 100 + index
        rows.append(
            {
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "close_time": 1_700_000_000_000 + index,
            }
        )

    signal = signal_from_klines("btcusdt", "15m", pd.DataFrame(rows))

    assert signal is not None
    assert signal.candidate_source == "simplified_placeholder"
    assert signal.candidate_source_version == "v1"
    assert signal.is_placeholder is True
    assert signal.edge_conclusions_allowed is False
    assert signal.direction_support == DirectionSupport.LONG_AND_SHORT.value
    assert signal.source_description == "MA/ATR simplified placeholder for technical live paper smoke testing only"
