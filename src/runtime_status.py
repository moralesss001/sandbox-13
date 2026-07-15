from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .candidate_sources import PLACEHOLDER_EDGE_WARNING, SIMPLIFIED_PLACEHOLDER_METADATA


DEFAULT_STATUS_PATH = Path("data/runtime/runtime_status.json")
_STATUS_FILE_LOCK = threading.RLock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_status() -> dict[str, Any]:
    now = utc_now()
    return {
        "mode": "paper",
        "interface_target": "telegram",
        "cli_is_fallback": True,
        "started_at": now,
        "updated_at": now,
        "symbols": [],
        "timeframe": None,
        "direction": "LONG",
        "candidate_mode": SIMPLIFIED_PLACEHOLDER_METADATA.candidate_source,
        **SIMPLIFIED_PLACEHOLDER_METADATA.as_status_fields(),
        "live_direction_policy": "LONG_ONLY",
        "last_iteration_at": None,
        "last_processed_candle_time": None,
        "last_processed_candles": {},
        "open_virtual_positions_count": 0,
        "open_positions_count": 0,
        "closed_trades_count": 0,
        "ignored_short_candidates_count": 0,
        "rejected_candidates_count": 0,
        "last_rejected_candidate_reason": None,
        "shadow_gates_enabled": True,
        "raw_candidates_count": 0,
        "production_would_allow_count": 0,
        "production_would_block_count": 0,
        "shadow_blocked_but_tracked_count": 0,
        "shadow_gate_block_counts": {
            "rsi_gate": 0,
            "market_mode_15m_gate": 0,
        },
        "last_shadow_block_reasons": [],
        "placeholder_edge_warning": PLACEHOLDER_EDGE_WARNING,
        "latest_report_path": None,
        "storage_paths": {
            "open_positions": "data/paper_trades/open_positions.json",
            "closed_trades": "data/paper_trades/closed_trades.csv",
            "runtime_status": "data/runtime/runtime_status.json",
        },
        "checkpoint_progress": {
            "closed_trades_count": 0,
            "next_checkpoint": 30,
        },
        "research_pack_2_enabled": False,
        "safety_status": {
            "api_mode": "paper",
            "allow_real_orders": False,
            "allow_testnet_orders": False,
            "telegram_read_only": True,
            "public_data_only": True,
            "private_api_used": False,
            "real_orders_enabled": False,
            "testnet_orders_enabled": False,
        },
        "errors": [],
    }


class RuntimeStatusStore:
    def __init__(self, path: str | Path = DEFAULT_STATUS_PATH):
        self.path = Path(path)

    def read(self) -> dict[str, Any]:
        with _STATUS_FILE_LOCK:
            if not self.path.exists():
                return default_status()
            return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, status: dict[str, Any]) -> dict[str, Any]:
        with _STATUS_FILE_LOCK:
            payload = dict(status)
            payload["updated_at"] = utc_now()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            temp_path.replace(self.path)
            return payload

    def update(self, **updates: Any) -> dict[str, Any]:
        with _STATUS_FILE_LOCK:
            status = self.read()
            status.update(updates)
            return self.write(status)

    def append_error(self, error: str, limit: int = 20) -> dict[str, Any]:
        with _STATUS_FILE_LOCK:
            status = self.read()
            errors = list(status.get("errors", []))
            errors.append({"timestamp": utc_now(), "error": error})
            status["errors"] = errors[-limit:]
            return self.write(status)


def portfolio_counts(portfolios: dict[str, Any]) -> tuple[int, int]:
    open_count = 0
    closed_count = 0
    for portfolio in portfolios.values():
        open_count += len(getattr(portfolio, "open_positions", []))
        closed_count += len(getattr(portfolio, "closed_trades", []))
    return open_count, closed_count
