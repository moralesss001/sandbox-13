from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .research_session_manager import ResearchSessionManager
from .runtime_status import RuntimeStatusStore, utc_now


_SECRET_KEY_FRAGMENTS = ("token", "secret", "password", "credential", "api_key", "private_key")
_TELEGRAM_TOKEN_PATTERN = re.compile(r"bot\d+:[A-Za-z0-9_-]+", re.IGNORECASE)


@dataclass(frozen=True)
class ExportDataResult:
    message: str
    documents: tuple[str, ...]


class TelegramDataExporter:
    """Build a secret-safe export for exactly one research session."""

    def __init__(
        self,
        data_root: str | Path = "data",
        status_store: RuntimeStatusStore | None = None,
        session_manager: ResearchSessionManager | None = None,
    ):
        self.session_manager = session_manager or ResearchSessionManager(
            data_root,
            global_status_path=status_store.path if status_store is not None else None,
        )
        self.status_store = status_store or self.session_manager.global_status_store
        self.export_root = self.session_manager.data_root / "runtime" / "telegram_export"

    def build(self, session_id: str | None = None) -> ExportDataResult:
        selected = self.session_manager.selected_session_id(session_id)
        if not selected:
            requested = f" {session_id}" if session_id else ""
            return ExportDataResult(f"Research session{requested} not found.", ())

        paths = self.session_manager.paths(selected)
        export_dir = self.export_root / selected
        export_dir.mkdir(parents=True, exist_ok=True)
        status = RuntimeStatusStore(paths.runtime_status).read()
        documents: list[str] = []
        missing: list[Path] = []
        issues: list[str] = []

        json_sources = [
            (paths.manifest, export_dir / "manifest.json"),
            (paths.config_snapshot, export_dir / "config_snapshot.json"),
            (paths.runtime_status, export_dir / "runtime_status.json"),
            (paths.open_positions, export_dir / "open_positions.json"),
        ]
        for source, target in json_sources:
            if not source.exists() or source.is_symlink():
                missing.append(source)
                continue
            try:
                value = json.loads(source.read_text(encoding="utf-8"))
                self._write_json_value(target, self._sanitize(value))
                documents.append(str(target))
            except (json.JSONDecodeError, OSError) as exc:
                issues.append(f"Unreadable session file: {source.name} ({type(exc).__name__})")

        csv_sources = [
            (paths.closed_trades, export_dir / "closed_trades.csv"),
            (paths.events / "hypothesis_events.csv", export_dir / "hypothesis_events.csv"),
            (paths.reports / "portfolio_snapshot.csv", export_dir / "portfolio_snapshot.csv"),
            (paths.reports / "paper_trades_snapshot.csv", export_dir / "paper_trades_snapshot.csv"),
        ]
        for source, target in csv_sources:
            if not source.exists() or source.is_symlink():
                missing.append(source)
                continue
            try:
                self._write_sanitized_csv(source, target)
                documents.append(str(target))
            except (csv.Error, OSError) as exc:
                issues.append(f"Unreadable session file: {source.name} ({type(exc).__name__})")

        latest_report = status.get("latest_report_path")
        if latest_report:
            report_path = Path(str(latest_report)).expanduser().resolve()
            try:
                report_path.relative_to(paths.reports.resolve())
            except ValueError:
                issues.append("Latest report path is outside the selected session and was excluded.")
            else:
                if report_path.exists() and not report_path.is_symlink():
                    target = export_dir / "final_report.md"
                    target.write_text(
                        str(self._sanitize(report_path.read_text(encoding="utf-8"))),
                        encoding="utf-8",
                    )
                    documents.append(str(target))

        summary_path = export_dir / "run_summary.json"
        self._write_json_value(
            summary_path,
            self._run_summary(selected, status, paths),
        )
        documents.append(str(summary_path))

        lines = [
            f"Session export prepared: {selected}",
            f"Safe files: {len(documents)}",
            "Sending:",
            *[f"- {Path(path).name}" for path in documents],
        ]
        if missing:
            lines.append("Unavailable:")
            lines.extend(f"- {path.name}" for path in missing)
        lines.extend(issues)
        lines.append("Legacy root files, .env, tokens and private API data are excluded.")
        return ExportDataResult("\n".join(lines), tuple(documents))

    def _run_summary(
        self,
        session_id: str,
        status: dict[str, Any],
        paths: Any,
    ) -> dict[str, Any]:
        global_status = self.status_store.read()
        configured = status.get("configured_symbols") or []
        active = status.get("active_symbols") or []
        unavailable = status.get("unavailable_symbols") or []
        return self._sanitize(
            {
                "generated_at": utc_now(),
                "session_id": session_id,
                "session_status": status.get("status"),
                "started_at": status.get("started_at"),
                "ended_at": status.get("ended_at"),
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
                "open_positions_count": int(status.get("open_positions_count") or 0),
                "closed_trades_count": int(status.get("closed_trades_count") or 0),
                "production_would_allow_count": int(status.get("production_would_allow_count") or 0),
                "production_would_block_count": int(status.get("production_would_block_count") or 0),
                "shadow_blocked_but_tracked_count": int(
                    status.get("shadow_blocked_but_tracked_count") or 0
                ),
                "unresolved_open_positions_count": int(
                    status.get("unresolved_open_positions_count") or 0
                ),
                "lifetime_raw_candidates": int(global_status.get("lifetime_raw_candidates") or 0),
                "lifetime_closed_trades": int(global_status.get("lifetime_closed_trades") or 0),
                "session_storage_paths": paths.as_dict(),
            }
        )

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

    def _write_json_value(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(path)

    def _write_sanitized_csv(self, source: Path, target: Path) -> None:
        if source.stat().st_size == 0:
            target.write_text("", encoding="utf-8")
            return
        with source.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        if not fields:
            target.write_text("", encoding="utf-8")
            return
        temp_path = target.with_suffix(target.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(self._sanitize(rows))
        temp_path.replace(target)
