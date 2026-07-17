from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .live_paper_storage import LivePaperStorage
from .runtime_status import RuntimeStatusStore, utc_now


_SECRET_KEY_FRAGMENTS = ("token", "secret", "password", "credential", "api_key", "private_key")
_TELEGRAM_TOKEN_PATTERN = re.compile(r"bot\d+:[A-Za-z0-9_-]+", re.IGNORECASE)


@dataclass(frozen=True)
class ExportDataResult:
    message: str
    documents: tuple[str, ...]


class TelegramDataExporter:
    """Build an explicit, secret-safe export of live paper runtime artifacts."""

    def __init__(
        self,
        data_root: str | Path = "data",
        status_store: RuntimeStatusStore | None = None,
    ):
        self.storage = LivePaperStorage(data_root)
        self.status_store = status_store or RuntimeStatusStore(self.storage.runtime_status_path)
        self.export_dir = self.storage.data_root / "runtime" / "telegram_export"

    def build(self) -> ExportDataResult:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        status = self.status_store.read()
        diagnostics = self.storage.diagnostics()
        documents: list[str] = []
        missing: list[Path] = []
        issues: list[str] = []

        if self.status_store.path.exists():
            safe_status_path = self.export_dir / "runtime_status.json"
            self._write_json(safe_status_path, self._sanitize(status))
            documents.append(str(safe_status_path))
        else:
            missing.append(self.status_store.path)

        open_positions_export = self.export_dir / "open_positions.json"
        if self.storage.open_positions_path.exists() and not self.storage.open_positions_path.is_symlink():
            try:
                rows = json.loads(self.storage.open_positions_path.read_text(encoding="utf-8"))
                self._write_json_value(open_positions_export, self._sanitize(rows))
                documents.append(str(open_positions_export))
            except (json.JSONDecodeError, OSError) as exc:
                issues.append(f"Unreadable export file: {self.storage.open_positions_path.name} ({type(exc).__name__})")
        else:
            missing.append(self.storage.open_positions_path)

        closed_trades_export = self.export_dir / "closed_trades.csv"
        if self.storage.closed_trades_path.exists() and not self.storage.closed_trades_path.is_symlink():
            try:
                self._write_sanitized_csv(self.storage.closed_trades_path, closed_trades_export)
                documents.append(str(closed_trades_export))
            except (csv.Error, OSError) as exc:
                issues.append(f"Unreadable export file: {self.storage.closed_trades_path.name} ({type(exc).__name__})")
        else:
            missing.append(self.storage.closed_trades_path)

        run_summary_path = self.export_dir / "run_summary.json"
        self._write_json(run_summary_path, self._run_summary(status, diagnostics))
        documents.append(str(run_summary_path))

        lines = [f"Export prepared: {len(documents)} safe file(s).", "Sending:"]
        lines.extend(f"- {Path(path).name}" for path in documents)
        if missing:
            lines.append("Unavailable:")
            lines.extend(f"- {path.name}" for path in missing)
        lines.extend(issues)
        lines.append("Only allowlisted paper/runtime files are included; secrets and .env are excluded.")
        return ExportDataResult("\n".join(lines), tuple(documents))

    def _run_summary(self, status: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
        errors = status.get("errors") or []
        configured = status.get("configured_symbols") or status.get("symbols") or []
        active = status.get("active_symbols") or []
        unavailable = status.get("unavailable_symbols") or []
        return {
            "generated_at": utc_now(),
            "control_state": status.get("control_state") or "stopped",
            "candidate_source": status.get("candidate_source"),
            "candidate_source_version": status.get("candidate_source_version"),
            "timeframe": status.get("timeframe"),
            "direction": status.get("direction") or status.get("live_direction_policy"),
            "configured_symbols": configured,
            "configured_symbols_count": len(configured),
            "active_symbols": active,
            "active_symbols_count": len(active),
            "unavailable_symbols": unavailable,
            "unavailable_symbols_count": len(unavailable),
            "raw_candidates_count": int(status.get("raw_candidates_count") or 0),
            "raw_candidates_current_run": int(status.get("raw_candidates_current_run") or 0),
            "raw_candidates_lifetime": int(
                status.get("raw_candidates_lifetime", status.get("raw_candidates_count", 0)) or 0
            ),
            "open_virtual_positions_count": int(
                status.get("open_virtual_positions_count", status.get("open_positions_count", 0)) or 0
            ),
            "open_positions_current": int(
                status.get("open_positions_current", status.get("open_positions_count", 0)) or 0
            ),
            "closed_trades_count": int(status.get("closed_trades_count") or 0),
            "closed_trades_lifetime": int(
                status.get("closed_trades_lifetime", status.get("closed_trades_count", 0)) or 0
            ),
            "production_would_allow_count": int(status.get("production_would_allow_count") or 0),
            "production_would_block_count": int(status.get("production_would_block_count") or 0),
            "shadow_blocked_but_tracked_count": int(status.get("shadow_blocked_but_tracked_count") or 0),
            "errors": len(errors) if isinstance(errors, list) else int(errors or 0),
            "runtime_data_directory": diagnostics["runtime_data_directory"],
            "runtime_status_path": diagnostics["runtime_status_path"],
            "open_positions_path": diagnostics["open_positions_path"],
            "closed_trades_path": diagnostics["closed_trades_path"],
        }

    def _sanitize(self, value: Any, key: str = "") -> Any:
        normalized_key = key.lower()
        if any(fragment in normalized_key for fragment in _SECRET_KEY_FRAGMENTS):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {item_key: self._sanitize(item, item_key) for item_key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize(item, key) for item in value]
        if isinstance(value, str):
            return _TELEGRAM_TOKEN_PATTERN.sub("bot[REDACTED]", value)
        return value

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self._write_json_value(path, self._sanitize(payload))

    def _write_json_value(self, path: Path, payload: Any) -> None:
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(path)

    def _write_sanitized_csv(self, source: Path, target: Path) -> None:
        with source.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        if not fields:
            target.write_text("", encoding="utf-8")
            return
        temp_path = target.with_suffix(".csv.tmp")
        with temp_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(self._sanitize(rows))
        temp_path.replace(target)
