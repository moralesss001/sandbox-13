from __future__ import annotations

from pathlib import Path

import pandas as pd

from .journal_loader import load_journal_csv
from .market_context import build_market_context
from .risk_mode import determine_risk_mode
from .session_classifier import classify_session
from .strategy_mode import determine_strategy_mode


def decide_shadow(strategy_mode: str, risk_mode: str) -> str:
    if risk_mode == "NO_RISK" or strategy_mode == "NO_TRADE":
        return "NO_TRADE"
    if risk_mode == "REDUCED_RISK":
        return "REDUCE_RISK"
    return "ALLOW"


class ReplayEngine:
    def run(self, file_path: str | Path, timeframe: str = "15m") -> tuple[pd.DataFrame, list[str]]:
        df, warnings = load_journal_csv(file_path, timeframe=timeframe)
        records = []
        for _, row in df.iterrows():
            context = build_market_context(row)
            session = classify_session(row)
            strategy = determine_strategy_mode(context, session)
            risk = determine_risk_mode(context, session, strategy.mode)
            decision = decide_shadow(strategy.mode, risk.mode)

            record = row.to_dict()
            record.update(
                {
                    "rsi_zone": context.rsi_zone,
                    "volatility_state": context.volatility_state,
                    "session_shadow": session,
                    "strategy_mode_shadow": strategy.mode,
                    "strategy_reason_shadow": strategy.reason,
                    "risk_mode_shadow": risk.mode,
                    "risk_reason_shadow": risk.reason,
                    "decision_shadow": decision,
                }
            )
            records.append(record)
            warnings.extend(context.warnings)

        warnings = list(dict.fromkeys(warnings))
        replay_df = pd.DataFrame(records)
        replay_df.attrs.update(df.attrs)
        return replay_df, warnings
