from __future__ import annotations

import csv
import io
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from .order_models import Position, Trade


_STORAGE_LOCK = threading.RLock()


class ClosedTradesRollbackError(OSError):
    pass


class ClosedTradesSchemaError(RuntimeError):
    pass


class LivePaperStorage:
    def __init__(
        self,
        data_root: str | Path = "data",
        runtime_status_path: str | Path | None = None,
    ):
        self.data_root = Path(data_root).expanduser().resolve()
        self.open_positions_path = self.data_root / "paper_trades" / "open_positions.json"
        self.closed_trades_path = self.data_root / "paper_trades" / "closed_trades.csv"
        self.runtime_status_path = (
            Path(runtime_status_path).expanduser().resolve()
            if runtime_status_path is not None
            else self.data_root / "runtime" / "runtime_status.json"
        )
        self.open_positions_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_status_path.parent.mkdir(parents=True, exist_ok=True)
        self._closed_identities: set[str] | None = None
        self._closed_signal_ids: set[str] | None = None
        self._closed_count: int | None = None
        self._closed_signature: tuple[int, int, int] | None = None
        self._closed_rows_snapshot: list[dict[str, Any]] | None = None

    def paths(self) -> dict[str, str]:
        return {
            "open_positions": str(self.open_positions_path),
            "closed_trades": str(self.closed_trades_path),
            "runtime_status": str(self.runtime_status_path),
        }

    def diagnostics(self) -> dict[str, Any]:
        diagnostics = {
            "runtime_data_directory": str(self.data_root),
            "runtime_status_path": str(self.runtime_status_path),
            "open_positions_path": str(self.open_positions_path),
            "closed_trades_path": str(self.closed_trades_path),
            "paths_exist": {
                "runtime_data_directory": self.data_root.exists(),
                "runtime_status": self.runtime_status_path.exists(),
                "open_positions": self.open_positions_path.exists(),
                "closed_trades": self.closed_trades_path.exists(),
            },
        }
        try:
            usage = shutil.disk_usage(self.data_root)
            used_pct = (usage.used / usage.total * 100.0) if usage.total else 0.0
            if used_pct >= 95.0:
                level = "critical"
            elif used_pct >= 85.0:
                level = "high"
            elif used_pct >= 70.0:
                level = "warning"
            else:
                level = "normal"
            diagnostics["storage_usage"] = {
                "available": True,
                "total_bytes": int(usage.total),
                "used_bytes": int(usage.used),
                "free_bytes": int(usage.free),
                "used_percent": round(used_pct, 2),
                "level": level,
                "warning": None if level == "normal" else f"storage_usage_{level}",
            }
        except Exception as exc:  # noqa: BLE001 - diagnostics must never stop research.
            diagnostics["storage_usage"] = {
                "available": False,
                "level": "unknown",
                "warning": f"disk_stats_unavailable:{type(exc).__name__}",
            }
        return diagnostics

    def load_open_positions(self) -> list[Position]:
        with _STORAGE_LOCK:
            if not self.open_positions_path.exists():
                return []
            try:
                raw = json.loads(self.open_positions_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Corrupted open positions storage: {self.open_positions_path}") from exc
            if not isinstance(raw, list):
                raise RuntimeError(f"Open positions storage must contain a list: {self.open_positions_path}")
            positions = [Position(**item) for item in raw]
            return self._unique_positions(positions)

    def restore_open_positions(
        self,
        portfolios: dict[str, Any],
        closed_signal_ids: set[str] | None = None,
    ) -> int:
        restored = 0
        closed_ids = closed_signal_ids or set()
        for position in self.load_open_positions():
            if position.signal_id and position.signal_id in closed_ids:
                continue
            portfolio = portfolios.get(position.hypothesis_id)
            if portfolio is None:
                continue
            if portfolio.add_open_position(position):
                restored += 1
        return restored

    def load_closed_trades(self) -> list[Trade]:
        with _STORAGE_LOCK:
            trades = []
            self._ensure_closed_indexes()
            rows = self._closed_rows_snapshot
            if rows is None:
                rows = self._read_closed_rows()
                self._cache_closed_indexes(rows)
            self._closed_rows_snapshot = None
            for row in rows:
                payload = self._deserialize_trade_row(row)
                required = {
                    "trade_id",
                    "hypothesis_id",
                    "symbol",
                    "timeframe",
                    "direction",
                    "entry_time",
                    "entry_price",
                    "tp",
                    "sl",
                    "rr_ratio",
                    "position_size_usdt",
                    "leverage",
                }
                if not required.issubset(payload):
                    continue
                try:
                    trades.append(Trade(**payload))
                except TypeError as exc:
                    raise RuntimeError(
                        f"Corrupted closed trades storage: {self.closed_trades_path}"
                    ) from exc
            return trades

    def restore_closed_trades(self, portfolios: dict[str, Any]) -> int:
        restored = 0
        for trade in self.load_closed_trades():
            portfolio = portfolios.get(trade.hypothesis_id)
            if portfolio is not None and portfolio.add_closed_trade(trade):
                restored += 1
        return restored

    def mark_open_positions_unresolved(
        self,
        closed_signal_ids: set[str] | None = None,
    ) -> int:
        closed_ids = closed_signal_ids or set()
        positions = [
            position
            for position in self.load_open_positions()
            if not position.signal_id or position.signal_id not in closed_ids
        ]
        for position in positions:
            position.session_final_status = "UNRESOLVED_AT_SESSION_END"
        rows = [dict(position.__dict__) for position in positions]
        with _STORAGE_LOCK:
            temp_path = self.open_positions_path.with_suffix(".json.tmp")
            temp_path.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temp_path.replace(self.open_positions_path)
        return len(positions)

    def save_open_positions(self, portfolios: dict[str, Any]) -> str:
        positions = []
        for portfolio in portfolios.values():
            positions.extend(portfolio.open_positions)
        rows = [dict(position.__dict__) for position in self._unique_positions(positions)]
        with _STORAGE_LOCK:
            self.open_positions_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.open_positions_path.with_suffix(".json.tmp")
            temp_path.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temp_path.replace(self.open_positions_path)
        return str(self.open_positions_path)

    def append_closed_trades(self, trades: list[Trade]) -> str:
        with _STORAGE_LOCK:
            self.closed_trades_path.parent.mkdir(parents=True, exist_ok=True)
            if not trades:
                if not self.closed_trades_path.exists():
                    self.closed_trades_path.touch()
                return str(self.closed_trades_path)

            self._ensure_closed_indexes()
            known = set(self._closed_identities or set())
            additions = []
            for trade in trades:
                row = self._serialize_trade_row(dict(trade.__dict__))
                identity = self._row_identity(row)
                if identity and identity in known:
                    continue
                additions.append(row)
                if identity:
                    known.add(identity)
            if additions:
                self._append_closed_rows(additions)
                self._closed_identities = known
                signal_ids = self._closed_signal_ids or set()
                signal_ids.update(
                    str(row["signal_id"])
                    for row in additions
                    if row.get("signal_id")
                )
                self._closed_signal_ids = signal_ids
                self._closed_count = int(self._closed_count or 0) + len(additions)
                self._closed_signature = self._closed_file_signature()
                self._closed_rows_snapshot = None
        return str(self.closed_trades_path)

    def _serialize_trade_row(self, row: dict[str, Any]) -> dict[str, Any]:
        for key in ["production_block_reasons", "shadow_gate_block_reasons"]:
            value = row.get(key)
            if isinstance(value, list):
                row[key] = "|".join(str(item) for item in value)
        if isinstance(row.get("shadow_gates"), list):
            row["shadow_gates"] = json.dumps(row["shadow_gates"], ensure_ascii=False, sort_keys=True)
        return row

    def _deserialize_trade_row(self, row: dict[str, Any]) -> dict[str, Any]:
        float_fields = {
            "entry_price",
            "tp",
            "sl",
            "rr_ratio",
            "position_size_usdt",
            "leverage",
            "rsi",
            "atr_pct",
            "atr",
            "sl_pct",
            "risk_distance",
            "reward_distance",
            "actual_rr",
            "exit_price",
            "r",
            "pnl_usdt",
            "fees_usdt",
            "slippage_usdt",
        }
        bool_fields = {
            "macd",
            "volume",
            "is_placeholder",
            "edge_conclusions_allowed",
            "production_would_allow",
        }
        list_fields = {"production_block_reasons", "shadow_gate_block_reasons"}
        payload: dict[str, Any] = {}
        for key in Trade.__dataclass_fields__:
            if key not in row:
                continue
            value = row.get(key)
            if value in {"", None}:
                continue
            if key in float_fields:
                payload[key] = float(value)
            elif key == "score":
                payload[key] = int(float(value))
            elif key in bool_fields:
                payload[key] = str(value).strip().lower() in {"1", "true", "yes"}
            elif key in list_fields:
                payload[key] = [item for item in str(value).split("|") if item]
            elif key == "shadow_gates":
                payload[key] = json.loads(value) if isinstance(value, str) else value
            else:
                payload[key] = value
        return payload

    def closed_trades_count(self) -> int:
        with _STORAGE_LOCK:
            self._ensure_closed_indexes()
            return int(self._closed_count or 0)

    def closed_signal_ids(self) -> set[str]:
        with _STORAGE_LOCK:
            self._ensure_closed_indexes()
            return set(self._closed_signal_ids or set())

    def _ensure_closed_indexes(self) -> None:
        signature = self._closed_file_signature()
        if self._closed_identities is not None and self._closed_signature == signature:
            return
        self._cache_closed_indexes(self._read_closed_rows())

    def _cache_closed_indexes(self, rows: list[dict[str, Any]]) -> None:
        self._closed_identities = {
            identity
            for row in rows
            if (identity := self._row_identity(row))
        }
        self._closed_signal_ids = {
            str(row["signal_id"])
            for row in rows
            if row.get("signal_id")
        }
        self._closed_count = len(rows)
        self._closed_signature = self._closed_file_signature()
        self._closed_rows_snapshot = rows

    def _closed_file_signature(self) -> tuple[int, int, int]:
        if not self.closed_trades_path.exists():
            return (0, 0, 0)
        stat = self.closed_trades_path.stat()
        return (int(stat.st_ino), int(stat.st_size), int(stat.st_mtime_ns))

    def _read_closed_rows(self) -> list[dict[str, Any]]:
        if not self.closed_trades_path.exists() or self.closed_trades_path.stat().st_size == 0:
            return []
        with self.closed_trades_path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def _append_closed_rows(self, rows: list[dict[str, Any]]) -> None:
        original_size = self.closed_trades_path.stat().st_size if self.closed_trades_path.exists() else 0
        fields = self._closed_fieldnames(rows, original_size)
        buffer = io.StringIO(newline="")
        if original_size and not self._closed_file_ends_with_newline():
            buffer.write("\n")
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        if original_size == 0:
            writer.writeheader()
        writer.writerows(rows)
        payload = buffer.getvalue().encode("utf-8")

        descriptor = os.open(
            self.closed_trades_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o644,
        )
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("closed trades append made no progress")
                view = view[written:]
            os.fsync(descriptor)
        except OSError as append_error:
            try:
                os.ftruncate(descriptor, original_size)
                os.fsync(descriptor)
            except OSError as rollback_error:
                raise ClosedTradesRollbackError(
                    rollback_error.errno or append_error.errno,
                    "closed trades append rollback failed",
                ) from append_error
            raise
        finally:
            os.close(descriptor)

    def _closed_fieldnames(self, rows: list[dict[str, Any]], original_size: int) -> list[str]:
        if original_size:
            with self.closed_trades_path.open("r", encoding="utf-8", newline="") as handle:
                fields = next(csv.reader(handle), [])
            if not fields:
                raise ClosedTradesSchemaError(
                    f"Closed trades CSV has no header: {self.closed_trades_path}"
                )
            extra_values = {
                key
                for row in rows
                for key, value in row.items()
                if key not in fields and value not in (None, "", [], {})
            }
            if extra_values:
                raise ClosedTradesSchemaError(
                    "Closed trades CSV schema mismatch; missing columns: "
                    + ", ".join(sorted(extra_values))
                )
            return fields
        return sorted({key for row in rows for key in row})

    def _closed_file_ends_with_newline(self) -> bool:
        with self.closed_trades_path.open("rb") as handle:
            handle.seek(-1, os.SEEK_END)
            return handle.read(1) in {b"\n", b"\r"}

    def _row_identity(self, row: dict[str, Any]) -> str | None:
        return str(row.get("signal_id") or row.get("trade_id") or "") or None

    def _unique_positions(self, positions: list[Position]) -> list[Position]:
        seen: set[str] = set()
        unique = []
        for position in positions:
            identity = str(position.signal_id or position.trade_id)
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(position)
        return unique
