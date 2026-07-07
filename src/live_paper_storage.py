from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .order_models import Position, Trade


class LivePaperStorage:
    def __init__(self, data_root: str | Path = "data"):
        self.data_root = Path(data_root)
        self.open_positions_path = self.data_root / "paper_trades" / "open_positions.json"
        self.closed_trades_path = self.data_root / "paper_trades" / "closed_trades.csv"
        self.runtime_status_path = self.data_root / "runtime" / "runtime_status.json"

    def paths(self) -> dict[str, str]:
        return {
            "open_positions": str(self.open_positions_path),
            "closed_trades": str(self.closed_trades_path),
            "runtime_status": str(self.runtime_status_path),
        }

    def load_open_positions(self) -> list[Position]:
        if not self.open_positions_path.exists():
            return []
        try:
            raw = json.loads(self.open_positions_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Corrupted open positions storage: {self.open_positions_path}") from exc
        if not isinstance(raw, list):
            raise RuntimeError(f"Open positions storage must contain a list: {self.open_positions_path}")
        return [Position(**item) for item in raw]

    def restore_open_positions(self, portfolios: dict[str, Any]) -> int:
        restored = 0
        for position in self.load_open_positions():
            portfolio = portfolios.get(position.hypothesis_id)
            if portfolio is None:
                continue
            portfolio.add_open_position(position)
            restored += 1
        return restored

    def save_open_positions(self, portfolios: dict[str, Any]) -> str:
        rows = []
        for portfolio in portfolios.values():
            rows.extend(dict(position.__dict__) for position in portfolio.open_positions)
        self.open_positions_path.parent.mkdir(parents=True, exist_ok=True)
        self.open_positions_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return str(self.open_positions_path)

    def append_closed_trades(self, trades: list[Trade]) -> str:
        self.closed_trades_path.parent.mkdir(parents=True, exist_ok=True)
        if not trades:
            if not self.closed_trades_path.exists():
                self.closed_trades_path.write_text("", encoding="utf-8")
            return str(self.closed_trades_path)

        rows = [self._serialize_trade_row(dict(trade.__dict__)) for trade in trades]
        fields = sorted({key for row in rows for key in row})
        write_header = not self.closed_trades_path.exists() or self.closed_trades_path.stat().st_size == 0
        with self.closed_trades_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerows(rows)
        return str(self.closed_trades_path)

    def _serialize_trade_row(self, row: dict[str, Any]) -> dict[str, Any]:
        for key in ["production_block_reasons", "shadow_gate_block_reasons"]:
            value = row.get(key)
            if isinstance(value, list):
                row[key] = "|".join(str(item) for item in value)
        if isinstance(row.get("shadow_gates"), list):
            row["shadow_gates"] = json.dumps(row["shadow_gates"], ensure_ascii=False, sort_keys=True)
        return row

    def closed_trades_count(self) -> int:
        if not self.closed_trades_path.exists() or self.closed_trades_path.stat().st_size == 0:
            return 0
        with self.closed_trades_path.open("r", encoding="utf-8", newline="") as handle:
            return max(0, sum(1 for _ in handle) - 1)
