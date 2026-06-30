from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_STATUS_PATH = Path("data/runtime/status.json")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_status() -> dict[str, Any]:
    now = utc_now()
    return {
        "mode": "paper",
        "started_at": now,
        "updated_at": now,
        "symbols": [],
        "timeframe": None,
        "last_iteration_at": None,
        "last_processed_candles": {},
        "open_positions_count": 0,
        "closed_trades_count": 0,
        "latest_report_path": None,
        "safety_status": {
            "api_mode": "paper",
            "allow_real_orders": False,
            "allow_testnet_orders": False,
            "telegram_read_only": True,
        },
        "errors": [],
    }


class RuntimeStatusStore:
    def __init__(self, path: str | Path = DEFAULT_STATUS_PATH):
        self.path = Path(path)

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return default_status()
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, status: dict[str, Any]) -> dict[str, Any]:
        payload = dict(status)
        payload["updated_at"] = utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def update(self, **updates: Any) -> dict[str, Any]:
        status = self.read()
        status.update(updates)
        return self.write(status)

    def append_error(self, error: str, limit: int = 20) -> dict[str, Any]:
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

