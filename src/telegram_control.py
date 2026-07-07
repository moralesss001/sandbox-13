from __future__ import annotations

from pathlib import Path
from datetime import datetime

import pandas as pd
import yaml

from .candidate_sources import PRODUCTION_LIKE_RAW_METADATA
from .command_queue import CommandQueue
from .hypothesis_registry import HypothesisRegistry
from .runtime_status import RuntimeStatusStore
from .telegram_buttons import main_control_keyboard, start_live_confirmation_keyboard
from .telegram_live_paper import TelegramLivePaperReporter


class TelegramControlPanel:
    def __init__(
        self,
        status_store: RuntimeStatusStore | None = None,
        command_queue: CommandQueue | None = None,
        data_root: str | Path = "data",
    ):
        self.status_store = status_store or RuntimeStatusStore(Path(data_root) / "runtime/runtime_status.json")
        self.command_queue = command_queue or CommandQueue(Path(data_root) / "runtime/commands.jsonl")
        self.data_root = Path(data_root)
        self.registry = HypothesisRegistry()
        self.live_reporter = TelegramLivePaperReporter(self.status_store, self.data_root)

    def status(self) -> str:
        status = self.status_store.read()
        return "\n".join(
            [
                "Crypto13Research status",
                f"mode: {status.get('mode')}",
                f"updated_at: {status.get('updated_at')}",
                f"symbols: {', '.join(status.get('symbols') or [])}",
                f"timeframe: {status.get('timeframe')}",
                f"candidate_source: {status.get('candidate_source')}",
                f"candidate_source_version: {status.get('candidate_source_version')}",
                f"source_description: {status.get('source_description')}",
                f"edge_conclusions_allowed: {status.get('edge_conclusions_allowed')}",
                f"candidate_source_warning: {status.get('candidate_source_warning') or 'n/a'}",
                f"open_positions: {status.get('open_positions_count')}",
                f"closed_trades: {status.get('closed_trades_count')}",
                f"latest_report: {status.get('latest_report_path') or 'n/a'}",
                f"errors: {len(status.get('errors') or [])}",
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
                    "Confirm Start Live Paper",
                    "Mode: paper only",
                    "candidate_source: production_like_raw",
                    "timeframe: 15m",
                    "direction: LONG_ONLY",
                    "Real orders: disabled",
                    "Testnet orders: disabled",
                    "This queues START_LIVE_PAPER for the separate sandbox engine process.",
                ]
            ),
            start_live_confirmation_keyboard(),
        )

    def live_start(self, requested_by: str) -> str:
        status = self.status_store.read()
        control_state = str(status.get("control_state") or "stopped")
        if control_state in {"running", "start_requested"}:
            return "\n".join(["Live paper already running or start already requested.", "", self.live_status()])

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
        self.status_store.update(
            mode="live_paper",
            control_state="start_requested",
            symbols=symbols,
            timeframe="15m",
            direction="LONG",
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
            return "Live paper is not running. No stop command queued."
        return self.stop_live_research(requested_by)

    def stop_live_research(self, requested_by: str) -> str:
        command = self.command_queue.enqueue("STOP_LIVE_RESEARCH", requested_by=requested_by)
        report_path = self._write_stop_report(command.command_id)
        self.status_store.update(
            mode="paper",
            control_state="stop_requested",
            stop_requested_at=datetime.now().isoformat(timespec="seconds"),
            latest_report_path=str(report_path),
        )
        return "\n".join(
            [
                f"Queued safe command: {command.command} ({command.command_id})",
                "Live research stop requested.",
                "Paper artifacts will be flushed by the engine on stop.",
                f"Final stop report: {report_path}",
            ]
        )

    def restart_live_research(self, requested_by: str) -> str:
        command = self.command_queue.enqueue("RESTART_LIVE_RESEARCH", requested_by=requested_by)
        self.status_store.update(mode="paper", control_state="restart_requested")
        return f"Queued safe command: {command.command} ({command.command_id})"

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
