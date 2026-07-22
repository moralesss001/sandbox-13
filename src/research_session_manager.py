from __future__ import annotations

import csv
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .runtime_status import RuntimeStatusStore, utc_now


GLOBAL_STATUS_FILENAME = "global_runtime_status.json"
LEGACY_SESSION_ID = "legacy_session_unscoped"
_SESSION_LOCK = threading.RLock()
_SESSION_ID_PATTERN = re.compile(r"^research-\d{8}T\d{12}Z-[0-9a-f]{8}$")


@dataclass(frozen=True)
class SessionPaths:
    root: Path
    manifest: Path
    config_snapshot: Path
    runtime_status: Path
    open_positions: Path
    closed_trades: Path
    events: Path
    reports: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "session_root": str(self.root),
            "manifest": str(self.manifest),
            "config_snapshot": str(self.config_snapshot),
            "runtime_status": str(self.runtime_status),
            "open_positions": str(self.open_positions),
            "closed_trades": str(self.closed_trades),
            "events": str(self.events),
            "reports": str(self.reports),
        }


class ResearchSessionManager:
    def __init__(
        self,
        data_root: str | Path = "data",
        global_status_path: str | Path | None = None,
    ):
        self.data_root = Path(data_root).expanduser().resolve()
        self.sessions_root = self.data_root / "sessions"
        self.index_path = self.sessions_root / "index.json"
        self.legacy_index_path = self.sessions_root / "legacy_index.json"
        self.global_status_path = (
            Path(global_status_path).expanduser().resolve()
            if global_status_path is not None
            else self.data_root / "runtime" / GLOBAL_STATUS_FILENAME
        )
        self.legacy_status_path = self.data_root / "runtime" / "runtime_status.json"
        self.legacy_open_positions_path = self.data_root / "paper_trades" / "open_positions.json"
        self.legacy_closed_trades_path = self.data_root / "paper_trades" / "closed_trades.csv"

    @property
    def global_status_store(self) -> RuntimeStatusStore:
        return RuntimeStatusStore(self.global_status_path)

    def ensure_initialized(self, service_defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        with _SESSION_LOCK:
            self.sessions_root.mkdir(parents=True, exist_ok=True)
            self.global_status_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_legacy_reference_once()
            if self.global_status_path.exists():
                status = self.global_status_store.read()
                if service_defaults:
                    status.update(service_defaults)
                    status = self.global_status_store.write(status)
                return status

            legacy = self._read_json(self.legacy_status_path, {})
            lifetime_raw = int(
                legacy.get("raw_candidates_lifetime", legacy.get("raw_candidates_count", 0)) or 0
            )
            lifetime_closed = self._legacy_closed_count()
            errors = list(legacy.get("errors") or [])
            status = {
                "mode": "sandbox_run_all",
                "runtime_layout": "single_service",
                "control_state": "stopped",
                "service_started_at": utc_now(),
                "active_session_id": None,
                "last_session_id": None,
                "legacy_session_id": LEGACY_SESSION_ID,
                "lifetime_raw_candidates": lifetime_raw,
                "raw_candidates_lifetime": lifetime_raw,
                "lifetime_closed_trades": lifetime_closed,
                "closed_trades_lifetime": lifetime_closed,
                "lifetime_errors": errors,
                "errors": errors[-20:],
                "processed_command_ids": list(legacy.get("processed_command_ids") or []),
                "session_id": None,
                "session_status": "stopped",
                "session_started_at": None,
                "session_ended_at": None,
                "raw_candidates_count": 0,
                "raw_candidates_current_run": 0,
                "closed_trades_count": 0,
                "open_positions_count": 0,
                "open_positions_current": 0,
                "production_would_allow_count": 0,
                "production_would_block_count": 0,
                "shadow_blocked_but_tracked_count": 0,
                "last_processed_candles": {},
                "latest_report_path": None,
                "legacy_storage_paths": {
                    "runtime_status": str(self.legacy_status_path),
                    "open_positions": str(self.legacy_open_positions_path),
                    "closed_trades": str(self.legacy_closed_trades_path),
                },
            }
            status.update(service_defaults or {})
            return self.global_status_store.write(status)

    def create_session(self, config_snapshot: dict[str, Any]) -> tuple[str, SessionPaths]:
        with _SESSION_LOCK:
            global_status = self.ensure_initialized()
            if (
                str(global_status.get("control_state") or "stopped") != "stopped"
                or global_status.get("active_session_id")
            ):
                raise RuntimeError("A new research session requires control_state=stopped")

            session_id, paths = self._allocate_session_paths()
            now = utc_now()
            snapshot = dict(config_snapshot)
            snapshot.update({"session_id": session_id, "created_at": now})
            self._write_json_exclusive(paths.config_snapshot, snapshot)
            paths.open_positions.write_text("[]\n", encoding="utf-8")
            paths.closed_trades.write_text("", encoding="utf-8")

            session_status = {
                "session_id": session_id,
                "status": "preparing",
                "started_at": now,
                "ended_at": None,
                "candidate_source": snapshot.get("candidate_source"),
                "candidate_source_version": snapshot.get("candidate_source_version"),
                "timeframe": snapshot.get("timeframe"),
                "direction": snapshot.get("direction"),
                "configured_symbols": list(snapshot.get("configured_symbols") or []),
                "active_symbols": [],
                "active_symbols_count": 0,
                "unavailable_symbols": [],
                "unavailable_symbols_count": 0,
                "unavailable_symbol_reasons": {},
                "raw_candidates_count": 0,
                "production_would_allow_count": 0,
                "production_would_block_count": 0,
                "shadow_blocked_but_tracked_count": 0,
                "shadow_gate_block_counts": {},
                "open_positions_count": 0,
                "closed_trades_count": 0,
                "last_processed_candle_time": None,
                "last_processed_candles": {},
                "errors": [],
                "latest_report_path": None,
                "unresolved_open_positions_count": 0,
                "safety_status": dict(snapshot.get("safety") or {}),
                "storage_paths": paths.as_dict(),
            }
            RuntimeStatusStore(paths.runtime_status).write(session_status)
            manifest = {
                "session_id": session_id,
                "status": "preparing",
                "created_at": now,
                "started_at": now,
                "ended_at": None,
                "timezone": "UTC",
                "candidate_source": snapshot.get("candidate_source"),
                "candidate_source_version": snapshot.get("candidate_source_version"),
                "timeframe": snapshot.get("timeframe"),
                "direction": snapshot.get("direction"),
                "configured_symbols": list(snapshot.get("configured_symbols") or []),
                "active_symbols": [],
                "unavailable_symbols": [],
                "hypothesis_registry": snapshot.get("hypotheses"),
                "code_revision": snapshot.get("code_revision"),
                "storage_paths": paths.as_dict(),
                "stop_reason": None,
                "unresolved_open_positions_count": 0,
                "legacy": False,
            }
            self._write_json_exclusive(paths.manifest, manifest)
            self._append_index(manifest)
            self.global_status_store.update(
                control_state="session_preparing",
                active_session_id=session_id,
                session_id=session_id,
                session_status="preparing",
                session_started_at=now,
                session_ended_at=None,
                raw_candidates_count=0,
                raw_candidates_current_run=0,
                closed_trades_count=0,
                open_positions_count=0,
                open_positions_current=0,
                production_would_allow_count=0,
                production_would_block_count=0,
                shadow_blocked_but_tracked_count=0,
                last_processed_candles={},
                last_processed_candle_time=None,
                latest_report_path=None,
                active_session_paths=paths.as_dict(),
            )
            return session_id, paths

    def mark_start_requested(self, session_id: str) -> None:
        with _SESSION_LOCK:
            global_status = self.global_status_store.read()
            if (
                global_status.get("active_session_id") != session_id
                or global_status.get("control_state") != "session_preparing"
            ):
                raise RuntimeError("Prepared research session is no longer active")
            paths = self.paths(session_id)
            self.session_status_store(session_id).update(status="start_requested")
            manifest = self._read_json(paths.manifest, {})
            manifest["status"] = "start_requested"
            self._write_json_atomic(paths.manifest, manifest)
            self._replace_index_entry(manifest)
            self.global_status_store.update(
                control_state="start_requested",
                session_status="start_requested",
            )

    def write_failure_report(
        self,
        session_id: str,
        *,
        reason: str,
        unresolved_open_positions_count: int,
    ) -> Path:
        paths = self.paths(session_id)
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        report_path = paths.reports / f"engine_failure_report_{suffix}.md"
        lines = [
            "# Crypto13Research Engine Failure Report",
            "",
            f"- Session id: {session_id}",
            f"- Reason: {reason}",
            f"- Generated at: {utc_now()}",
            f"- Unresolved open positions: {int(unresolved_open_positions_count)}",
            "- No synthetic exits were created.",
            "- Real and testnet orders remained disabled.",
        ]
        with report_path.open("x", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return report_path

    def finalize_session(
        self,
        session_id: str,
        *,
        stop_reason: str,
        unresolved_open_positions_count: int,
        latest_report_path: str | None,
        active_symbols: list[str] | None = None,
        unavailable_symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        with _SESSION_LOCK:
            paths = self.paths(session_id)
            ended_at = utc_now()
            session_store = RuntimeStatusStore(paths.runtime_status)
            session_status = session_store.update(
                status="stopped",
                ended_at=ended_at,
                unresolved_open_positions_count=int(unresolved_open_positions_count),
                latest_report_path=latest_report_path,
            )
            manifest = self._read_json(paths.manifest, {})
            manifest.update(
                {
                    "status": "stopped",
                    "ended_at": ended_at,
                    "stop_reason": stop_reason,
                    "unresolved_open_positions_count": int(unresolved_open_positions_count),
                    "active_symbols": list(active_symbols or session_status.get("active_symbols") or []),
                    "unavailable_symbols": list(
                        unavailable_symbols or session_status.get("unavailable_symbols") or []
                    ),
                    "latest_report_path": latest_report_path,
                }
            )
            self._write_json_atomic(paths.manifest, manifest)
            self._replace_index_entry(manifest)

            global_status = self.global_status_store.read()
            if global_status.get("active_session_id") == session_id:
                self.global_status_store.update(
                    control_state="stopped",
                    active_session_id=None,
                    active_session_paths=None,
                    last_session_id=session_id,
                    session_id=session_id,
                    session_status="stopped",
                    session_ended_at=ended_at,
                    unresolved_open_positions_count=int(unresolved_open_positions_count),
                    latest_report_path=latest_report_path,
                    live_engine_enabled=False,
                )
            return manifest

    def paths(self, session_id: str) -> SessionPaths:
        if not _SESSION_ID_PATTERN.fullmatch(str(session_id)):
            raise ValueError(f"Invalid research session_id: {session_id}")
        root = self.sessions_root / session_id
        return SessionPaths(
            root=root,
            manifest=root / "manifest.json",
            config_snapshot=root / "config_snapshot.json",
            runtime_status=root / "runtime_status.json",
            open_positions=root / "paper_trades" / "open_positions.json",
            closed_trades=root / "paper_trades" / "closed_trades.csv",
            events=root / "events",
            reports=root / "reports",
        )

    def session_status_store(self, session_id: str) -> RuntimeStatusStore:
        return RuntimeStatusStore(self.paths(session_id).runtime_status)

    def selected_session_id(self, explicit_session_id: str | None = None) -> str | None:
        if explicit_session_id:
            candidate = explicit_session_id.strip()
            if not _SESSION_ID_PATTERN.fullmatch(candidate):
                return None
            return candidate if self.paths(candidate).manifest.exists() else None
        status = self.ensure_initialized()
        return status.get("active_session_id") or status.get("last_session_id")

    def _allocate_session_paths(self) -> tuple[str, SessionPaths]:
        for _ in range(20):
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            session_id = f"research-{timestamp}-{uuid4().hex[:8]}"
            paths = self.paths(session_id)
            try:
                paths.root.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                continue
            paths.open_positions.parent.mkdir(parents=True, exist_ok=False)
            paths.events.mkdir(parents=True, exist_ok=False)
            paths.reports.mkdir(parents=True, exist_ok=False)
            return session_id, paths
        raise RuntimeError("Unable to allocate unique research session_id")

    def _write_legacy_reference_once(self) -> None:
        payload = {
            "session_id": LEGACY_SESSION_ID,
            "legacy": True,
            "status": "unscoped",
            "created_at": utc_now(),
            "paths": {
                "runtime_status": str(self.legacy_status_path),
                "open_positions": str(self.legacy_open_positions_path),
                "closed_trades": str(self.legacy_closed_trades_path),
            },
            "note": "Reference only. Legacy files are not moved, rewritten, or retroactively partitioned.",
        }
        if not self.legacy_index_path.exists():
            self._write_json_exclusive(self.legacy_index_path, payload)
        if not self.index_path.exists():
            self._write_json_exclusive(self.index_path, {"sessions": [payload]})
            return
        index = self._read_json(self.index_path, {"sessions": []})
        sessions = list(index.get("sessions") or [])
        if not any(item.get("session_id") == LEGACY_SESSION_ID for item in sessions):
            sessions.insert(0, payload)
            self._write_json_atomic(self.index_path, {"sessions": sessions})

    def _legacy_closed_count(self) -> int:
        if not self.legacy_closed_trades_path.exists() or self.legacy_closed_trades_path.stat().st_size == 0:
            return 0
        try:
            with self.legacy_closed_trades_path.open("r", encoding="utf-8", newline="") as handle:
                return sum(1 for _ in csv.DictReader(handle))
        except (OSError, csv.Error):
            return 0

    def _append_index(self, manifest: dict[str, Any]) -> None:
        index = self._read_json(self.index_path, {"sessions": []})
        sessions = list(index.get("sessions") or [])
        sessions.append(dict(manifest))
        self._write_json_atomic(self.index_path, {"sessions": sessions})

    def _replace_index_entry(self, manifest: dict[str, Any]) -> None:
        index = self._read_json(self.index_path, {"sessions": []})
        sessions = [
            dict(manifest) if item.get("session_id") == manifest.get("session_id") else item
            for item in list(index.get("sessions") or [])
        ]
        self._write_json_atomic(self.index_path, {"sessions": sessions})

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _write_json_exclusive(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")

    def _write_json_atomic(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
