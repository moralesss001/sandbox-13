from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .gate_analytics import summarize_gate_outcomes
from .runtime_status import RuntimeStatusStore


EDGE_WARNING = "Live paper is collecting evidence. Do not use this as production proof yet."


class TelegramLivePaperReporter:
    def __init__(self, status_store: RuntimeStatusStore, data_root: str | Path = "data"):
        self.status_store = status_store
        self.data_root = Path(data_root)

    def live_status(self) -> str:
        status = self.status_store.read()
        safety = status.get("safety_status") or {}
        return "\n".join(
            [
                "Live paper status",
                f"mode: {status.get('mode')}",
                f"control_state: {status.get('control_state') or 'stopped'}",
                f"candidate_source: {status.get('candidate_source')}",
                f"candidate_source_version: {status.get('candidate_source_version')}",
                f"timeframe: {status.get('timeframe')}",
                f"direction: {status.get('direction') or status.get('live_direction_policy')}",
                f"open_virtual_positions_count: {status.get('open_virtual_positions_count', status.get('open_positions_count', 0))}",
                f"closed_trades_count: {status.get('closed_trades_count', 0)}",
                f"raw_candidates_count: {status.get('raw_candidates_count', 0)}",
                f"production_would_allow_count: {status.get('production_would_allow_count', 0)}",
                f"production_would_block_count: {status.get('production_would_block_count', 0)}",
                f"shadow_blocked_but_tracked_count: {status.get('shadow_blocked_but_tracked_count', 0)}",
                f"last_processed_candle_time: {status.get('last_processed_candle_time') or 'n/a'}",
                f"last_shadow_block_reasons: {self._join(status.get('last_shadow_block_reasons') or [])}",
                f"errors: {len(status.get('errors') or [])}",
                f"edge_conclusions_allowed: {status.get('edge_conclusions_allowed')}",
                EDGE_WARNING,
                "Safety:",
                f"public_data_only: {safety.get('public_data_only', True)}",
                f"private_api_used: {safety.get('private_api_used', False)}",
                f"real_orders_enabled: {safety.get('real_orders_enabled', False)}",
                f"testnet_orders_enabled: {safety.get('testnet_orders_enabled', False)}",
                "production_code_changed: false",
            ]
        )

    def source(self) -> str:
        status = self.status_store.read()
        return "\n".join(
            [
                "Candidate source",
                f"candidate_source: {status.get('candidate_source')}",
                f"candidate_source_version: {status.get('candidate_source_version')}",
                f"is_placeholder: {status.get('is_placeholder')}",
                f"edge_conclusions_allowed: {status.get('edge_conclusions_allowed')}",
                f"direction_support: {status.get('direction_support')}",
                f"source_description: {status.get('source_description')}",
                "score_analytics_only: true",
                "score_used_as_gate: false",
                f"shadow_gates_enabled: {status.get('shadow_gates_enabled', True)}",
                EDGE_WARNING,
            ]
        )

    def open_trades(self, limit: int = 10) -> str:
        path = self.data_root / "paper_trades/open_positions.json"
        if not path.exists() or path.stat().st_size == 0:
            return "No open virtual positions."
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return f"Open positions storage is unreadable: {path}"
        if not rows:
            return "No open virtual positions."
        lines = [f"Open virtual positions: {min(len(rows), limit)} of {len(rows)}"]
        for row in rows[-limit:]:
            lines.extend(
                [
                    "",
                    f"symbol: {row.get('symbol')}",
                    f"direction: {row.get('direction')}",
                    f"entry: {row.get('entry_price')}",
                    f"tp: {row.get('tp')}",
                    f"sl: {row.get('sl')}",
                    f"opened_at: {row.get('entry_time')}",
                    f"candidate_source: {row.get('candidate_source')}",
                    f"production_would_allow: {row.get('production_would_allow')}",
                    f"production_block_reasons: {self._join(row.get('production_block_reasons') or [])}",
                    f"shadow_gate_block_reasons: {self._join(row.get('shadow_gate_block_reasons') or [])}",
                ]
            )
        return "\n".join(lines)

    def closed_trades(self, limit: int = 5) -> str:
        path = self.data_root / "paper_trades/closed_trades.csv"
        if not path.exists() or path.stat().st_size == 0:
            return "No closed paper trades yet."
        df = pd.read_csv(path)
        if df.empty:
            return "No closed paper trades yet."
        lines = [f"Latest closed paper trades: {min(len(df), limit)} of {len(df)}"]
        for row in df.tail(limit).to_dict("records"):
            lines.extend(
                [
                    "",
                    f"symbol: {row.get('symbol')}",
                    f"direction: {row.get('direction')}",
                    f"entry: {row.get('entry_price')}",
                    f"exit: {row.get('exit_price')}",
                    f"result: {row.get('result')} / R={row.get('r')}",
                    f"close_reason: {row.get('close_reason', row.get('exit_reason', row.get('reason', 'n/a')))}",
                    f"candidate_source: {row.get('candidate_source')}",
                    f"production_would_allow: {row.get('production_would_allow')}",
                    f"production_block_reasons: {row.get('production_block_reasons', '')}",
                ]
            )
        return "\n".join(lines)

    def gates(self) -> str:
        status = self.status_store.read()
        trades = self._closed_trade_rows()
        summary = summarize_gate_outcomes(trades)
        lines = ["Shadow gate analytics"]
        if not trades:
            lines.append("Not enough closed trades yet. Showing counters only.")
        lines.extend(
            [
                f"gate_saved_from_loss: {summary['gate_saved_from_loss']}",
                f"gate_missed_profit: {summary['gate_missed_profit']}",
                f"gate_allowed_loss: {summary['gate_allowed_loss']}",
                f"gate_allowed_profit: {summary['gate_allowed_profit']}",
                f"production_would_allow_count: {status.get('production_would_allow_count', 0)}",
                f"production_would_block_count: {status.get('production_would_block_count', 0)}",
                f"shadow_blocked_but_tracked_count: {status.get('shadow_blocked_but_tracked_count', 0)}",
                f"shadow_gate_block_counts: {json.dumps(status.get('shadow_gate_block_counts') or {}, ensure_ascii=False, sort_keys=True)}",
                f"last_shadow_block_reasons: {self._join(status.get('last_shadow_block_reasons') or [])}",
                EDGE_WARNING,
            ]
        )
        return "\n".join(lines)

    def _closed_trade_rows(self) -> list[dict[str, Any]]:
        path = self.data_root / "paper_trades/closed_trades.csv"
        if not path.exists() or path.stat().st_size == 0:
            return []
        df = pd.read_csv(path)
        return df.to_dict("records") if not df.empty else []

    def _join(self, value: Any) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, str):
            return value or "n/a"
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item) for item in value) if value else "n/a"
        return str(value)
