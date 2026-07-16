from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import yaml

from .candidate_sources import PRODUCTION_LIKE_RAW_METADATA
from .command_queue import CommandQueue
from .hypothesis_registry import HypothesisRegistry
from .runtime_status import RuntimeStatusStore
from .telegram_buttons import (
    diagnostics_keyboard,
    main_control_keyboard,
    start_live_confirmation_keyboard,
    stop_live_confirmation_keyboard,
)
from .telegram_export import ExportDataResult, TelegramDataExporter
from .telegram_live_paper import TelegramLivePaperReporter


class TelegramControlPanel:
    def __init__(
        self,
        status_store: RuntimeStatusStore | None = None,
        command_queue: CommandQueue | None = None,
        data_root: str | Path = "data",
    ):
        self.data_root = Path(data_root).expanduser().resolve()
        self.status_store = status_store or RuntimeStatusStore(self.data_root / "runtime/runtime_status.json")
        self.command_queue = command_queue or CommandQueue(self.data_root / "runtime/commands.jsonl")
        self.registry = HypothesisRegistry()
        self.live_reporter = TelegramLivePaperReporter(self.status_store, self.data_root)
        self.data_exporter = TelegramDataExporter(self.data_root, self.status_store)

    def status(self) -> str:
        status = self.status_store.read()
        control_state = str(status.get("control_state") or "stopped")
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
                f"runtime: {self._runtime_duration(status) if control_state != 'stopped' else 'stopped'}",
                f"raw candidates (current run): {status.get('raw_candidates_current_run', 0)}",
                f"open positions (current): {status.get('open_positions_current', status.get('open_positions_count', 0))}",
                f"closed trades (lifetime): {status.get('closed_trades_lifetime', status.get('closed_trades_count', 0))}",
                f"errors: {len(status.get('errors') or [])}",
                f"source: {status.get('candidate_source') or 'N/A'} {status.get('candidate_source_version') or 'N/A'}",
                f"market: {status.get('timeframe') or 'N/A'} / {status.get('direction') or status.get('live_direction_policy') or 'N/A'}",
                "execution: PAPER ONLY",
            ]
        )

    def settings(self) -> str:
        status = self.status_store.read()
        gate_counts = status.get("shadow_gate_block_counts") or {}
        enabled_gates = len(gate_counts) if status.get("shadow_gates_enabled") and isinstance(gate_counts, dict) else 0
        return "\n".join(
            [
                "Research Settings (read-only)",
                f"source: {status.get('candidate_source') or 'N/A'}",
                f"source version: {status.get('candidate_source_version') or 'N/A'}",
                f"timeframe: {status.get('timeframe') or 'N/A'}",
                f"direction: {status.get('direction') or status.get('live_direction_policy') or 'N/A'}",
                f"symbols: {', '.join(status.get('symbols') or []) or 'N/A'}",
                f"RR: {status.get('rr_ratio') or status.get('rr') or 'N/A'}",
                f"enabled hypotheses: {len(self.registry.enabled())}",
                f"enabled shadow gates: {enabled_gates}",
                "execution: PAPER ONLY",
                "real orders: OFF",
            ]
        )

    def diagnostics(self) -> str:
        status = self.status_store.read()
        diagnostics = self.data_exporter.storage.diagnostics()
        errors = status.get("errors") or []
        last_error = self._last_error_class(errors)
        reasons = status.get("last_shadow_block_reasons") or []
        last_reason = str(reasons[-1]) if isinstance(reasons, list) and reasons else "N/A"
        reason_count = len(reasons) if isinstance(reasons, list) else int(bool(reasons))
        return "\n".join(
            [
                "Live Research Diagnostics",
                f"mode: {status.get('mode') or 'N/A'}",
                f"runtime layout: {status.get('runtime_layout') or 'N/A'}",
                f"control state: {status.get('control_state') or 'stopped'}",
                f"engine state: {status.get('engine_state') or status.get('control_state') or 'stopped'}",
                f"runtime data: {diagnostics['runtime_data_directory']}",
                f"runtime status: {diagnostics['runtime_status_path']}",
                f"open positions: {diagnostics['open_positions_path']}",
                f"closed trades: {diagnostics['closed_trades_path']}",
                f"paths exist: {diagnostics['paths_exist']}",
                f"last candle: {status.get('last_processed_candle_time') or 'N/A'}",
                f"last error class: {last_error}",
                f"production allow count: {status.get('production_would_allow_count', 0)}",
                f"production block count: {status.get('production_would_block_count', 0)}",
                f"shadow blocked but tracked: {status.get('shadow_blocked_but_tracked_count', 0)}",
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
                    "production_like_raw v1",
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
        if control_state in {"running", "start_requested"}:
            return "Research is already running."

        symbols = self._default_live_symbols(status)
        payload = {
            "candidate_source": PRODUCTION_LIKE_RAW_METADATA.candidate_source,
            "candidate_source_version": PRODUCTION_LIKE_RAW_METADATA.candidate_source_version,
            "timeframe": "15m",
            "direction": "LONG_ONLY",
            "symbols": symbols,
            "mode": "live_paper",
        }
        command = self.command_queue.enqueue("START_LIVE_PAPER", requested_by=requested_by, payload=payload)
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
            control_state="start_requested",
            symbols=symbols,
            timeframe="15m",
            direction=direction,
            live_direction_policy="LONG_ONLY",
            candidate_mode=PRODUCTION_LIKE_RAW_METADATA.candidate_source,
            **PRODUCTION_LIKE_RAW_METADATA.as_status_fields(),
            shadow_gates_enabled=True,
            safety_status=safety_status,
        )
        return "\n".join(
            [
                f"Queued safe command: {command.command} ({command.command_id})",
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
        command = self.command_queue.enqueue("STOP_LIVE_RESEARCH", requested_by=requested_by)
        report_path = self._write_stop_report(command.command_id)
        status = self.status_store.read()
        mode_updates = {} if status.get("runtime_layout") == "single_service" else {"mode": "paper"}
        self.status_store.update(
            **mode_updates,
            control_state="stop_requested",
            stop_requested_at=datetime.now().isoformat(timespec="seconds"),
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
        command = self.command_queue.enqueue("RESTART_LIVE_RESEARCH", requested_by=requested_by)
        status = self.status_store.read()
        mode_updates = {} if status.get("runtime_layout") == "single_service" else {"mode": "paper"}
        self.status_store.update(**mode_updates, control_state="restart_requested")
        return f"Queued safe command: {command.command} ({command.command_id})"

    def export_data(self) -> ExportDataResult:
        return self.data_exporter.build()

    def latest_report(self) -> str:
        status_path = self.status_store.read().get("latest_report_path")
        latest = Path(status_path) if status_path else self._latest_file(self.data_root / "demo_reports", "demo_report_*.md")
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
        latest = self._latest_file(self.data_root / "paper_portfolios", "portfolio_snapshots_*.csv")
        if not latest:
            return "No paper portfolio snapshot found."
        df = pd.read_csv(latest)
        columns = [col for col in ["hypothesis_id", "total_trades", "net_R", "profit_factor", "winrate"] if col in df.columns]
        return f"Portfolio snapshot: {latest}\n" + df[columns].head(15).to_markdown(index=False)

    def events(self) -> str:
        latest = self._latest_file(self.data_root / "hypothesis_events", "hypothesis_events_*.csv")
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
        current = [str(symbol).upper() for symbol in (status.get("symbols") or []) if str(symbol).strip()]
        if current:
            return current
        config_path = Path("config/research_config.yaml")
        if config_path.exists():
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            symbols = data.get("live_research", {}).get("symbols") or []
            normalized = [str(symbol).upper() for symbol in symbols if str(symbol).strip()]
            if normalized:
                return normalized
        return ["BTCUSDT"]

    def _write_stop_report(self, command_id: str) -> Path:
        reports_dir = self.data_root / "demo_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"stop_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        status = self.status_store.read()
        latest_portfolio = self._latest_file(self.data_root / "paper_portfolios", "portfolio_snapshots_*.csv")
        latest_events = self._latest_file(self.data_root / "hypothesis_events", "hypothesis_events_*.csv")
        latest_trades = self._latest_file(self.data_root / "paper_trades", "paper_trades_*.csv")
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
