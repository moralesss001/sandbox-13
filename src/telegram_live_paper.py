from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .gate_analytics import summarize_gate_outcomes
from .live_paper_storage import LivePaperStorage
from .research_session_manager import ResearchSessionManager
from .runtime_status import RuntimeStatusStore


EDGE_WARNING = "Live paper is collecting evidence. Do not use this as production proof yet."


class TelegramLivePaperReporter:
    def __init__(
        self,
        status_store: RuntimeStatusStore,
        data_root: str | Path = "data",
        session_manager: ResearchSessionManager | None = None,
    ):
        self.status_store = status_store
        self.session_manager = session_manager or ResearchSessionManager(
            data_root,
            global_status_path=status_store.path,
        )
        self.data_root = self.session_manager.data_root

    @property
    def storage(self) -> LivePaperStorage:
        selected = self.session_manager.selected_session_id()
        if not selected:
            return LivePaperStorage(self.data_root)
        paths = self.session_manager.paths(selected)
        return LivePaperStorage(paths.root, runtime_status_path=paths.runtime_status)

    def live_status(self) -> str:
        global_status = self.status_store.read()
        session_id, status, storage = self._selected()
        safety = global_status.get("safety_status") or {}
        if not session_id:
            return "\n".join(
                [
                    "Live paper status",
                    f"control_state: {global_status.get('control_state') or 'stopped'}",
                    "selected_session_id: none",
                    "No research session has been created yet.",
                    EDGE_WARNING,
                    "Safety:",
                    f"public_data_only: {safety.get('public_data_only', True)}",
                    f"private_api_used: {safety.get('private_api_used', False)}",
                    f"real_orders_enabled: {safety.get('real_orders_enabled', False)}",
                    f"testnet_orders_enabled: {safety.get('testnet_orders_enabled', False)}",
                ]
            )
        return "\n".join(
            [
                "Live paper status",
                f"control_state: {global_status.get('control_state') or 'stopped'}",
                f"selected_session_id: {session_id}",
                f"session_status: {status.get('status') or 'unknown'}",
                f"candidate_source: {status.get('candidate_source')}",
                f"candidate_source_version: {status.get('candidate_source_version')}",
                f"timeframe: {status.get('timeframe')}",
                f"direction: {status.get('direction') or status.get('live_direction_policy')}",
                f"session_raw_candidates: {status.get('raw_candidates_count', 0)}",
                f"session_open_positions: {status.get('open_positions_count', 0)}",
                f"session_closed_trades: {status.get('closed_trades_count', 0)}",
                f"lifetime_raw_candidates: {global_status.get('lifetime_raw_candidates', 0)}",
                f"lifetime_closed_trades: {global_status.get('lifetime_closed_trades', 0)}",
                f"production_would_allow_count: {status.get('production_would_allow_count', 0)}",
                f"production_would_block_count: {status.get('production_would_block_count', 0)}",
                f"shadow_blocked_but_tracked_count: {status.get('shadow_blocked_but_tracked_count', 0)}",
                f"last_processed_candle_time: {status.get('last_processed_candle_time') or 'n/a'}",
                f"session_errors: {len(status.get('errors') or [])}",
                f"session_data_directory: {storage.data_root}",
                f"session_runtime_status_path: {storage.runtime_status_path}",
                f"session_open_positions_path: {storage.open_positions_path}",
                f"session_closed_trades_path: {storage.closed_trades_path}",
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
        global_status = self.status_store.read()
        _session_id, status, _storage = self._selected()
        source_status = status or global_status
        return "\n".join(
            [
                "Candidate source",
                f"candidate_source: {source_status.get('candidate_source')}",
                f"candidate_source_version: {source_status.get('candidate_source_version')}",
                f"is_placeholder: {source_status.get('is_placeholder')}",
                f"edge_conclusions_allowed: {source_status.get('edge_conclusions_allowed')}",
                f"direction_support: {source_status.get('direction_support')}",
                f"source_description: {source_status.get('source_description')}",
                "score_analytics_only: true",
                "score_used_as_gate: false",
                f"shadow_gates_enabled: {source_status.get('shadow_gates_enabled', True)}",
                EDGE_WARNING,
            ]
        )

    def open_trades(self, limit: int = 10) -> str:
        session_id, _status, storage = self._selected()
        if not session_id:
            return "No open virtual positions."
        path = storage.open_positions_path
        if not path.exists() or path.stat().st_size == 0:
            return "No open virtual positions."
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return f"Open positions storage is unreadable: {path}"
        if not rows:
            return "No open virtual positions."
        lines = [f"Session {session_id}", f"Open virtual positions: {min(len(rows), limit)} of {len(rows)}"]
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
                    f"session_final_status: {row.get('session_final_status') or 'ACTIVE'}",
                    f"candidate_source: {row.get('candidate_source')}",
                    f"production_would_allow: {row.get('production_would_allow')}",
                    f"production_block_reasons: {self._join(row.get('production_block_reasons') or [])}",
                ]
            )
        return "\n".join(lines)

    def closed_trades(self, limit: int = 5) -> str:
        session_id, _status, storage = self._selected()
        if not session_id:
            return "No closed paper trades yet."
        path = storage.closed_trades_path
        if not path.exists() or path.stat().st_size == 0:
            return "No closed paper trades yet."
        df = pd.read_csv(path)
        if df.empty:
            return "No closed paper trades yet."
        lines = [f"Session {session_id}", f"Latest closed paper trades: {min(len(df), limit)} of {len(df)}"]
        for row in df.tail(limit).to_dict("records"):
            lines.extend(
                [
                    "",
                    f"symbol: {row.get('symbol')}",
                    f"direction: {row.get('direction')}",
                    f"entry: {row.get('entry_price')}",
                    f"exit: {row.get('exit_price')}",
                    f"result: {row.get('result')} / R={row.get('r')}",
                    f"candidate_source: {row.get('candidate_source')}",
                    f"production_would_allow: {row.get('production_would_allow')}",
                    f"production_block_reasons: {row.get('production_block_reasons', '')}",
                ]
            )
        return "\n".join(lines)

    def gates(self) -> str:
        session_id, status, storage = self._selected()
        if not session_id:
            summary = summarize_gate_outcomes([])
            return "\n".join(
                [
                    "Shadow gate analytics",
                    "Not enough closed trades yet. Showing session counters only.",
                    f"gate_saved_from_loss: {summary['gate_saved_from_loss']}",
                    f"gate_missed_profit: {summary['gate_missed_profit']}",
                    f"gate_allowed_loss: {summary['gate_allowed_loss']}",
                    f"gate_allowed_profit: {summary['gate_allowed_profit']}",
                    "production_would_allow_count: 0",
                    "production_would_block_count: 0",
                    "shadow_blocked_but_tracked_count: 0",
                    EDGE_WARNING,
                ]
            )
        trades = self._closed_trade_rows(storage)
        summary = summarize_gate_outcomes(trades)
        lines = [f"Shadow gate analytics: {session_id}"]
        if not trades:
            lines.append("Not enough closed trades yet. Showing session counters only.")
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

    def _selected(self) -> tuple[str | None, dict[str, Any], LivePaperStorage]:
        session_id = self.session_manager.selected_session_id()
        if not session_id:
            return None, {}, LivePaperStorage(self.data_root)
        paths = self.session_manager.paths(session_id)
        status = RuntimeStatusStore(paths.runtime_status).read()
        return session_id, status, LivePaperStorage(
            paths.root,
            runtime_status_path=paths.runtime_status,
        )

    def _closed_trade_rows(self, storage: LivePaperStorage) -> list[dict[str, Any]]:
        path = storage.closed_trades_path
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
