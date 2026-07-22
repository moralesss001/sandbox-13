from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

from .candidate_sources import PRODUCTION_LIKE_RAW_METADATA
from .command_queue import CommandQueue
from .hypothesis_registry import HypothesisRegistry
from .research_session_manager import ResearchSessionManager
from .runtime_status import RuntimeStatusStore
from .telegram_buttons import (
    diagnostics_keyboard,
    main_control_keyboard,
    start_live_confirmation_keyboard,
    stop_live_confirmation_keyboard,
)
from .telegram_export import ExportDataResult, TelegramDataExporter
from .telegram_live_paper import TelegramLivePaperReporter
from .universe import configured_universe


class TelegramControlPanel:
    def __init__(
        self,
        status_store: RuntimeStatusStore | None = None,
        command_queue: CommandQueue | None = None,
        data_root: str | Path = "data",
    ):
        self.data_root = Path(data_root).expanduser().resolve()
        self.session_manager = ResearchSessionManager(
            self.data_root,
            global_status_path=status_store.path if status_store is not None else None,
        )
        self.status_store = status_store or self.session_manager.global_status_store
        self.session_manager.ensure_initialized()
        self.command_queue = command_queue or CommandQueue(self.data_root / "runtime/commands.jsonl")
        self.registry = HypothesisRegistry()
        self.live_reporter = TelegramLivePaperReporter(
            self.status_store,
            self.data_root,
            session_manager=self.session_manager,
        )
        self.data_exporter = TelegramDataExporter(
            self.data_root,
            self.status_store,
            session_manager=self.session_manager,
        )

    def status(self) -> str:
        status = self.status_store.read()
        control_state = str(status.get("control_state") or "stopped")
        session_status = self._selected_session_status(status)
        configured = status.get("configured_symbols") or status.get("symbols") or []
        active = status.get("active_symbols") or []
        unavailable = status.get("unavailable_symbols") or []
        state_title = {
            "running": "🟢 Research Running",
            "start_requested": "🟡 Research Starting",
            "stop_requested": "🟡 Research Stopping",
            "restart_requested": "🟡 Research Restarting",
            "stopped": "⚪ Research Stopped",
        }.get(control_state, "⚪ Research Stopped")
        return "\n".join(
            [
                state_title,
                f"service state: {control_state}",
                f"active session ID: {status.get('active_session_id') or 'none'}",
                f"last completed session ID: {status.get('last_session_id') or 'none'}",
                f"session status: {session_status.get('status', 'none')}",
                f"session started_at: {session_status.get('started_at') or 'none'}",
                f"session runtime: {self._runtime_duration(session_status) if session_status else 'stopped'}",
                f"session raw candidates: {session_status.get('raw_candidates_count', 0)}",
                f"session open positions: {session_status.get('open_positions_count', 0)}",
                f"session closed trades: {session_status.get('closed_trades_count', 0)}",
                f"raw candidates (current run): {session_status.get('raw_candidates_count', 0)}",
                f"lifetime raw candidates: {status.get('lifetime_raw_candidates', status.get('raw_candidates_lifetime', 0))}",
                f"lifetime closed trades: {status.get('lifetime_closed_trades', status.get('closed_trades_lifetime', 0))}",
                f"closed trades (lifetime): {status.get('lifetime_closed_trades', status.get('closed_trades_lifetime', 0))}",
                f"unresolved positions previous session: {status.get('unresolved_open_positions_count', 0)}",
                f"session errors: {len(session_status.get('errors') or [])}",
                f"lifetime errors: {len(status.get('lifetime_errors') or status.get('errors') or [])}",
                f"source: {status.get('candidate_source') or 'N/A'} {status.get('candidate_source_version') or 'N/A'}",
                f"market: {status.get('timeframe') or 'N/A'} / {status.get('direction') or status.get('live_direction_policy') or 'N/A'}",
                f"universe: {len(configured)} configured / {len(active)} active / {len(unavailable)} unavailable",
                "execution: PAPER ONLY",
            ]
        )

    def settings(self) -> str:
        status = self.status_store.read()
        session_status = self._selected_session_status(status)
        configured = status.get("configured_symbols") or status.get("symbols") or []
        active = status.get("active_symbols") or []
        unavailable = status.get("unavailable_symbols") or []
        gate_counts = session_status.get("shadow_gate_block_counts") or {}
        enabled_gates = len(gate_counts) if status.get("shadow_gates_enabled") and isinstance(gate_counts, dict) else 0
        return "\n".join(
            [
                "Research Settings (read-only)",
                f"source: {status.get('candidate_source') or 'N/A'}",
                f"source version: {status.get('candidate_source_version') or 'N/A'}",
                f"timeframe: {status.get('timeframe') or 'N/A'}",
                f"direction: {status.get('direction') or status.get('live_direction_policy') or 'N/A'}",
                f"configured symbols: {len(configured)}",
                f"active symbols: {len(active)}",
                f"unavailable symbols: {', '.join(unavailable) or 'none'}",
                f"RR: {status.get('rr_ratio') or status.get('rr') or 'N/A'}",
                f"enabled hypotheses: {len(self.registry.enabled())}",
                f"enabled shadow gates: {enabled_gates}",
                "execution: PAPER ONLY",
                "real orders: OFF",
            ]
        )

    def diagnostics(self) -> str:
        status = self.status_store.read()
        session_status = self._selected_session_status(status)
        configured = status.get("configured_symbols") or status.get("symbols") or []
        active = status.get("active_symbols") or []
        unavailable = status.get("unavailable_symbols") or []
        diagnostics = self.live_reporter.storage.diagnostics()
        errors = session_status.get("errors") or status.get("errors") or []
        last_error = self._last_error_class(errors)
        reasons = session_status.get("last_shadow_block_reasons") or status.get("last_shadow_block_reasons") or []
        last_reason = str(reasons[-1]) if isinstance(reasons, list) and reasons else "N/A"
        reason_count = len(reasons) if isinstance(reasons, list) else int(bool(reasons))
        return "\n".join(
            [
                "Live Research Diagnostics",
                f"mode: {status.get('mode') or 'N/A'}",
                f"runtime layout: {status.get('runtime_layout') or 'N/A'}",
                f"control state: {status.get('control_state') or 'stopped'}",
                f"active session ID: {status.get('active_session_id') or 'none'}",
                f"last session ID: {status.get('last_session_id') or 'none'}",
                f"session state: {session_status.get('status', 'none')}",
                f"engine state: {status.get('engine_state') or status.get('control_state') or 'stopped'}",
                f"runtime data: {diagnostics['runtime_data_directory']}",
                f"runtime status: {diagnostics['runtime_status_path']}",
                f"open positions: {diagnostics['open_positions_path']}",
                f"closed trades: {diagnostics['closed_trades_path']}",
                f"paths exist: {diagnostics['paths_exist']}",
                f"configured universe count: {len(configured)}",
                f"active runtime universe count: {len(active)}",
                f"unavailable symbols: {', '.join(unavailable) or 'none'}",
                f"last candle: {session_status.get('last_processed_candle_time') or 'N/A'}",
                f"last error class: {last_error}",
                f"session production allow count: {session_status.get('production_would_allow_count', 0)}",
                f"session production block count: {session_status.get('production_would_block_count', 0)}",
                f"session shadow blocked but tracked: {session_status.get('shadow_blocked_but_tracked_count', 0)}",
                f"lifetime raw candidates: {status.get('lifetime_raw_candidates', 0)}",
                f"lifetime closed trades: {status.get('lifetime_closed_trades', 0)}",
                f"last shadow reason: {last_reason}",
                f"last shadow reason count: {reason_count}",
                "execution: PAPER ONLY",
            ]
        )

    def safety(self) -> str:
        safety = self.status_store.read().get("safety_status", {})
        return "\n".join(
            [
                "Safety status",
                f"api_mode: {safety.get('api_mode', 'paper')}",
                f"allow_real_orders: {safety.get('allow_real_orders', False)}",
                f"allow_testnet_orders: {safety.get('allow_testnet_orders', False)}",
                f"telegram_read_only: {safety.get('telegram_read_only', True)}",
                f"public_data_only: {safety.get('public_data_only', True)}",
                f"private_api_used: {safety.get('private_api_used', False)}",
                f"real_orders_enabled: {safety.get('real_orders_enabled', False)}",
                f"testnet_orders_enabled: {safety.get('testnet_orders_enabled', False)}",
                "production_code_changed: false",
                "production_trading: disabled",
            ]
        )

    def hypotheses(self) -> str:
        return "\n".join(h.hypothesis_id for h in self.registry.enabled())

    def hypothesis(self, hypothesis_id: str) -> str:
        hypothesis = self.registry.get(hypothesis_id)
        return "\n".join(
            [
                hypothesis.hypothesis_id,
                hypothesis.name,
                hypothesis.description,
                f"enabled: {hypothesis.enabled}",
                f"priority: {hypothesis.priority}",
                "rules:",
                *[f"- {rule}" for rule in hypothesis.rules],
            ]
        )

    def run_hypotheses(self, requested_by: str) -> str:
        command = self.command_queue.enqueue("RUN_HYPOTHESIS_REPLAY", requested_by=requested_by)
        return f"Queued safe command: {command.command} ({command.command_id})"

    def start_live_confirmation(self) -> tuple[str, dict]:
        return (
            "\n".join(
                [
                    "Start Live Paper Research?",
                    "",
                    "Source:",
                    f"production_like_raw {PRODUCTION_LIKE_RAW_METADATA.candidate_source_version}",
                    "",
                    "Mode:",
                    "15m LONG_ONLY",
                    "",
                    "Execution:",
                    "PAPER ONLY",
                    "",
                    "Real orders:",
                    "OFF",
                ]
            ),
            start_live_confirmation_keyboard(),
        )

    def stop_live_confirmation(self) -> tuple[str, dict]:
        return (
            "\n".join(
                [
                    "Stop Live Paper Research?",
                    "",
                    "New candidates and positions will no longer be created.",
                    "Current runtime data will be saved.",
                    "Telegram will remain online.",
                ]
            ),
            stop_live_confirmation_keyboard(),
        )

    def live_start(self, requested_by: str) -> str:
        status = self.status_store.read()
        control_state = str(status.get("control_state") or "stopped")
        if control_state != "stopped":
            if control_state in {"running", "start_requested"}:
                return "Research is already running."
            return f"Research Start rejected: service state is {control_state}. Wait for stopped."

        symbols = self._default_live_symbols(status)
        payload = {
            "candidate_source": PRODUCTION_LIKE_RAW_METADATA.candidate_source,
            "candidate_source_version": PRODUCTION_LIKE_RAW_METADATA.candidate_source_version,
            "timeframe": "15m",
            "direction": "LONG_ONLY",
            "symbols": symbols,
            "mode": "live_paper",
        }
        snapshot = self._build_config_snapshot(status, symbols)
        session_id, _paths = self.session_manager.create_session(snapshot)
        payload["session_id"] = session_id
        try:
            command = self.command_queue.enqueue("START_LIVE_PAPER", requested_by=requested_by, payload=payload)
            self.session_manager.mark_start_requested(session_id)
        except Exception:
            self.session_manager.finalize_session(
                session_id,
                stop_reason="start_queue_failed",
                unresolved_open_positions_count=0,
                latest_report_path=None,
            )
            raise
        safety_status = {
            **(status.get("safety_status") or {}),
            "api_mode": "paper",
            "telegram_read_only": True,
            "public_data_only": True,
            "private_api_used": False,
            "real_orders_enabled": False,
            "testnet_orders_enabled": False,
        }
        mode_updates = {} if status.get("runtime_layout") == "single_service" else {"mode": "live_paper"}
        direction = "LONG_ONLY" if status.get("runtime_layout") == "single_service" else "LONG"
        self.status_store.update(
            **mode_updates,
            symbols=symbols,
            timeframe="15m",
            direction=direction,
            live_direction_policy="LONG_ONLY",
            candidate_mode=PRODUCTION_LIKE_RAW_METADATA.candidate_source,
            **PRODUCTION_LIKE_RAW_METADATA.as_status_fields(),
            shadow_gates_enabled=True,
            safety_status=safety_status,
            active_session_id=session_id,
            session_id=session_id,
            session_status="start_requested",
        )
        return "\n".join(
            [
                f"Queued safe command: {command.command} ({command.command_id})",
                f"session_id: {session_id}",
                "Live paper start requested for sandbox engine.",
                f"symbols: {', '.join(symbols)}",
                "candidate_source: production_like_raw",
                "timeframe: 15m",
                "direction: LONG_ONLY",
                "Real/testnet orders remain disabled.",
            ]
        )

    def start_live_research(self, requested_by: str) -> str:
        return self.live_start(requested_by)

    def live_stop(self, requested_by: str) -> str:
        status = self.status_store.read()
        control_state = str(status.get("control_state") or "stopped")
        if control_state not in {"running", "start_requested", "restart_requested"}:
            return "Research is not running."
        return self.stop_live_research(requested_by)

    def stop_live_research(self, requested_by: str) -> str:
        status = self.status_store.read()
        session_id = status.get("active_session_id")
        command = self.command_queue.enqueue(
            "STOP_LIVE_RESEARCH",
            requested_by=requested_by,
            payload={"session_id": session_id} if session_id else {},
        )
        report_path = self._write_stop_report(command.command_id)
        mode_updates = {} if status.get("runtime_layout") == "single_service" else {"mode": "paper"}
        self.status_store.update(
            **mode_updates,
            control_state="stop_requested",
            stop_requested_at=datetime.now().isoformat(timespec="seconds"),
            latest_report_path=str(report_path),
        )
        if session_id:
            self.session_manager.session_status_store(str(session_id)).update(
                status="stop_requested",
                latest_report_path=str(report_path),
            )
        return "\n".join(
            [
                "Research stop requested.",
                "",
                "Telegram control panel remains online.",
                "Use Export Data to download current runtime files.",
            ]
        )

    def restart_live_research(self, requested_by: str) -> str:
        status = self.status_store.read()
        control_state = str(status.get("control_state") or "stopped")
        if control_state not in {"running", "start_requested"}:
            return "Research is not running."
        session_id = status.get("active_session_id")
        command = self.command_queue.enqueue(
            "RESTART_LIVE_RESEARCH",
            requested_by=requested_by,
            payload={"session_id": session_id} if session_id else {},
        )
        mode_updates = {} if status.get("runtime_layout") == "single_service" else {"mode": "paper"}
        self.status_store.update(**mode_updates, control_state="stop_requested")
        if session_id:
            self.session_manager.session_status_store(str(session_id)).update(status="stop_requested")
        return (
            f"Queued safe command: {command.command} ({command.command_id})\n"
            "Current session will stop safely. Start a new independent session after state becomes stopped."
        )

    def export_data(self, session_id: str | None = None) -> ExportDataResult:
        return self.data_exporter.build(session_id=session_id)

    def latest_report(self) -> str:
        status = self.status_store.read()
        session_status = self._selected_session_status(status)
        status_path = session_status.get("latest_report_path") if session_status else None
        latest = Path(status_path) if status_path else None
        if not latest or not latest.exists():
            return "No demo report found."
        text = latest.read_text(encoding="utf-8").splitlines()
        summary = "\n".join(text[:20])
        return f"Latest report: {latest}\n\n{summary}"

    def suggestions(self) -> str:
        report = self.latest_report()
        lines = [line for line in report.splitlines() if "Candidates for testnet" in line or "candidate" in line.lower()]
        return "\n".join(lines[:20]) if lines else "No candidate suggestions found in latest report."

    def portfolio(self) -> str:
        session_id = self.session_manager.selected_session_id()
        latest = (
            self.session_manager.paths(session_id).reports / "portfolio_snapshot.csv"
            if session_id
            else None
        )
        if latest is not None and not latest.exists():
            latest = None
        if not latest:
            return "No paper portfolio snapshot found."
        df = pd.read_csv(latest)
        columns = [col for col in ["hypothesis_id", "total_trades", "net_R", "profit_factor", "winrate"] if col in df.columns]
        return f"Portfolio snapshot: {latest}\n" + df[columns].head(15).to_markdown(index=False)

    def events(self) -> str:
        session_id = self.session_manager.selected_session_id()
        latest = (
            self.session_manager.paths(session_id).events / "hypothesis_events.csv"
            if session_id
            else None
        )
        if latest is not None and not latest.exists():
            latest = None
        if not latest:
            return "No hypothesis events found."
        df = pd.read_csv(latest)
        columns = [col for col in ["timestamp", "hypothesis_id", "symbol", "decision", "block_reason"] if col in df.columns]
        return f"Recent events: {latest}\n" + df[columns].tail(15).to_markdown(index=False)

    def live_status(self) -> str:
        return self.live_reporter.live_status()

    def source(self) -> str:
        return self.live_reporter.source()

    def open_trades(self) -> str:
        return self.live_reporter.open_trades()

    def closed_trades(self) -> str:
        return self.live_reporter.closed_trades()

    def gates(self) -> str:
        return self.live_reporter.gates()

    def help(self) -> str:
        return "\n".join(
            [
                "Available commands:",
                "/start",
                "/live_start",
                "/live_stop",
                "/live_status",
                "/live_restart",
                "/settings",
                "/diagnostics",
                "/source",
                "/open_trades",
                "/closed_trades",
                "/gates",
                "/start_live",
                "/status",
                "/safety",
                "/hypotheses",
                "/hypothesis <id>",
                "/run_hypotheses",
                "/latest_report",
                "/suggestions",
                "/portfolio",
                "/events",
                "/export_data",
                "/help",
            ]
        )

    def _latest_file(self, root: Path, pattern: str) -> Path | None:
        if not root.exists():
            return None
        files = sorted(root.glob(pattern))
        return files[-1] if files else None

    def main_keyboard(self) -> dict:
        return main_control_keyboard()

    def diagnostics_keyboard(self) -> dict:
        return diagnostics_keyboard()

    def _default_live_symbols(self, status: dict) -> list[str]:
        return configured_universe()

    def _write_stop_report(self, command_id: str) -> Path:
        status = self.status_store.read()
        session_id = status.get("active_session_id")
        reports_dir = (
            self.session_manager.paths(str(session_id)).reports
            if session_id
            else self.data_root / "demo_reports"
        )
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"stop_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        status = self.status_store.read()
        session_paths = self.session_manager.paths(str(session_id)) if session_id else None
        latest_portfolio = session_paths.reports / "portfolio_snapshot.csv" if session_paths else None
        latest_events = session_paths.events / "hypothesis_events.csv" if session_paths else None
        latest_trades = session_paths.closed_trades if session_paths else None
        lines = [
            "# Crypto13Research Stop Report",
            "",
            "## Summary",
            f"- Command id: `{command_id}`",
            f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
            "- Stop requested by Telegram read-only control panel.",
            "- Engine is expected to flush paper portfolios, trades, and hypothesis events before exiting.",
            "",
            "## Runtime status",
            f"- Mode: {status.get('mode')}",
            f"- Symbols: {', '.join(status.get('symbols') or [])}",
            f"- Timeframe: {status.get('timeframe')}",
            f"- Open positions: {status.get('open_positions_count')}",
            f"- Closed trades: {status.get('closed_trades_count')}",
            f"- Errors: {len(status.get('errors') or [])}",
            "",
            "## Artifact paths",
            f"- Latest portfolio snapshot: `{latest_portfolio or 'n/a'}`",
            f"- Latest hypothesis events: `{latest_events or 'n/a'}`",
            f"- Latest paper trades: `{latest_trades or 'n/a'}`",
            "",
            "## Safety",
            "- API mode remains paper.",
            "- Real orders remain disabled.",
            "- Testnet orders remain disabled.",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _selected_session_status(self, global_status: dict) -> dict:
        session_id = global_status.get("active_session_id") or global_status.get("last_session_id")
        if not session_id:
            return {}
        path = self.session_manager.paths(str(session_id)).runtime_status
        return RuntimeStatusStore(path).read() if path.exists() else {}

    def _build_config_snapshot(self, status: dict, symbols: list[str]) -> dict:
        hypotheses = [
            {
                "hypothesis_id": item.hypothesis_id,
                "name": item.name,
                "enabled": item.enabled,
                "priority": item.priority,
                "rules": list(item.rules),
            }
            for item in self.registry.enabled()
        ]
        return {
            "timeframe": "15m",
            "direction": "LONG_ONLY",
            "candidate_source": PRODUCTION_LIKE_RAW_METADATA.candidate_source,
            "candidate_source_version": PRODUCTION_LIKE_RAW_METADATA.candidate_source_version,
            "configured_symbols": list(symbols),
            "hypotheses": hypotheses,
            "hard_shadow_gates": {
                "rsi": {"minimum": 35.0, "maximum": 65.0},
                "sl_pct": {"minimum": 0.0075, "maximum": 0.035},
                "pattern_against_long": True,
                "market_mode_15m": "analytics_only",
            },
            "rr_tp_sl": {"rr_ratio": 1.5, "sl_atr_multiplier": 1.5},
            "paper_trading": {
                "starting_balance_usdt": 1000.0,
                "default_position_size_usdt": 100.0,
                "leverage": 10.0,
                "fee_rate": 0.0004,
                "slippage_pct": 0.0005,
                "intrabar_policy": "conservative",
            },
            "safety": dict(status.get("safety_status") or {}),
            "code_revision": status.get("code_revision"),
        }

    def _runtime_duration(self, status: dict) -> str:
        started_at = status.get("started_at")
        if not started_at:
            return "N/A"
        try:
            started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            seconds = max(0, int((datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()))
        except (TypeError, ValueError):
            return "N/A"
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _last_error_class(self, errors: object) -> str:
        if not isinstance(errors, list) or not errors:
            return "N/A"
        latest = errors[-1]
        value = latest.get("error") if isinstance(latest, dict) else latest
        text = str(value or "N/A").splitlines()[0]
        error_class = text.split(":", maxsplit=1)[0].strip()
        if error_class.replace(".", "").replace("_", "").isalnum() and " " not in error_class:
            return error_class
        return "RecordedError"
