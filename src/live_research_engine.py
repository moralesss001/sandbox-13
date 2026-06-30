from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .binance_data import get_latest_klines
from .command_queue import CommandQueue
from .execution_safety import validate_api_mode
from .hypothesis_runner import HypothesisRunner
from .runtime_status import RuntimeStatusStore, portfolio_counts, utc_now
from .signal_adapter import signal_from_klines


class LiveResearchEngine:
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        data_root: str | Path = "data",
        status_store: RuntimeStatusStore | None = None,
        command_queue: CommandQueue | None = None,
    ):
        self.config = config or {}
        self.data_root = Path(data_root)
        self.status_store = status_store or RuntimeStatusStore(self.data_root / "runtime/status.json")
        self.command_queue = command_queue or CommandQueue(self.data_root / "runtime/commands.jsonl")
        self.public_base_url = self.config.get("api", {}).get("public_base_url", "https://fapi.binance.com")
        self.api_mode = validate_api_mode(
            {
                "mode": self.config.get("api", {}).get("mode", "paper"),
                **self.config.get("safety", {}),
            }
        )

    def run(
        self,
        symbols: list[str],
        timeframe: str,
        interval_sec: int = 60,
        max_iterations: int = 1,
        run_forever: bool = False,
    ) -> dict[str, Any]:
        paper_cfg = self.config.get("paper_trading", {})
        runner = HypothesisRunner(
            starting_balance_usdt=float(paper_cfg.get("starting_balance_usdt", 1000)),
            default_position_size_usdt=float(paper_cfg.get("default_position_size_usdt", 100)),
            leverage=float(paper_cfg.get("leverage", 10)),
            fee_rate=float(paper_cfg.get("fee_rate", 0.0004)),
            slippage_pct=float(paper_cfg.get("slippage_pct", 0.0005)),
            intrabar_policy=str(paper_cfg.get("intrabar_policy", "conservative")),
            data_root=self.data_root,
        )
        status = self.status_store.read()
        last_processed = dict(status.get("last_processed_candles") or {})
        symbols = [symbol.upper() for symbol in symbols]
        self.status_store.write(
            {
                **status,
                "mode": self.api_mode,
                "started_at": status.get("started_at") or utc_now(),
                "symbols": symbols,
                "timeframe": timeframe,
                "last_processed_candles": last_processed,
                "safety_status": {
                    "api_mode": self.api_mode,
                    "allow_real_orders": bool(self.config.get("safety", {}).get("allow_real_orders", False)),
                    "allow_testnet_orders": bool(self.config.get("safety", {}).get("allow_testnet_orders", False)),
                    "telegram_read_only": True,
                },
            }
        )

        index = 0
        while run_forever or index < max(1, int(max_iterations)):
            index += 1
            control_action = self._control_action()
            if control_action in {"STOP_LIVE_RESEARCH", "RESTART_LIVE_RESEARCH"}:
                paths = runner.save_artifacts()
                open_count, closed_count = portfolio_counts(runner.portfolios)
                report_path = self._write_engine_stop_report(runner, paths, reason=control_action)
                self.status_store.update(
                    control_state="stopped" if control_action == "STOP_LIVE_RESEARCH" else "restart_requested",
                    open_positions_count=open_count,
                    closed_trades_count=closed_count,
                    latest_report_path=str(report_path),
                    last_iteration_at=utc_now(),
                )
                return {
                    "portfolios": runner.portfolios,
                    "events": runner.events,
                    "metrics": runner.metrics(),
                    "paths": {**paths, "final_stop_report": str(report_path)},
                    "signal_source": "research_simplified_live",
                }
            for symbol in symbols:
                try:
                    klines = get_latest_klines(symbol, timeframe, limit=200, base_url=self.public_base_url)
                    self._save_live_market(symbol, timeframe, klines)
                    closed = self._latest_closed_klines(klines)
                    if closed.empty:
                        continue
                    close_time = str(closed.iloc[-1].get("close_time"))
                    key = f"{symbol}:{timeframe}"
                    if last_processed.get(key) == close_time:
                        continue
                    signal = signal_from_klines(symbol, timeframe, closed)
                    if signal:
                        runner.process_signal(signal, close_from_history=False)
                        last_processed[key] = close_time
                except Exception as exc:  # noqa: BLE001 - status file should capture transient API errors.
                    self.status_store.append_error(f"{symbol} {timeframe}: {exc}")
            paths = runner.save_artifacts()
            open_count, closed_count = portfolio_counts(runner.portfolios)
            self.status_store.update(
                last_iteration_at=utc_now(),
                last_processed_candles=last_processed,
                open_positions_count=open_count,
                closed_trades_count=closed_count,
                latest_report_path=self.status_store.read().get("latest_report_path"),
            )
            if run_forever or index < max(1, int(max_iterations)):
                time.sleep(max(1, int(interval_sec)))
        return {
            "portfolios": runner.portfolios,
            "events": runner.events,
            "metrics": runner.metrics(),
            "paths": paths,
            "signal_source": "research_simplified_live",
        }

    def mark_latest_report(self, report_path: str | Path) -> None:
        self.status_store.update(latest_report_path=str(report_path))

    def _save_live_market(self, symbol: str, timeframe: str, klines) -> None:
        date = datetime.now().strftime("%Y%m%d")
        path = self.data_root / "live_market" / f"live_market_{date}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = klines.copy()
        frame.insert(0, "symbol", symbol.upper())
        frame.insert(1, "timeframe", timeframe)
        frame.to_csv(path, mode="a", index=False, header=not path.exists())

    def _latest_closed_klines(self, klines):
        if klines.empty or "close_time" not in klines.columns:
            return klines.iloc[0:0].copy()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        closed = klines[klines["close_time"].astype("int64") <= now_ms].copy()
        return closed

    def _control_action(self) -> str | None:
        status = self.status_store.read()
        processed = set(status.get("processed_command_ids") or [])
        for command in self.command_queue.read_all():
            if command.command_id in processed:
                continue
            processed.add(command.command_id)
            self.status_store.update(processed_command_ids=sorted(processed), last_control_command=command.command)
            if command.command in {"STOP_LIVE_RESEARCH", "RESTART_LIVE_RESEARCH"}:
                return command.command
            if command.command == "START_LIVE_RESEARCH":
                self.status_store.update(control_state="running")
        return None

    def _write_engine_stop_report(self, runner: HypothesisRunner, paths: dict[str, str], reason: str) -> Path:
        reports_dir = self.data_root / "demo_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"engine_stop_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        open_count, closed_count = portfolio_counts(runner.portfolios)
        lines = [
            "# Crypto13Research Engine Stop Report",
            "",
            "## Summary",
            f"- Reason: `{reason}`",
            f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
            f"- Open virtual positions: {open_count}",
            f"- Closed virtual trades: {closed_count}",
            "",
            "## Flushed artifacts",
            f"- Paper trades: `{paths.get('paper_trades', 'n/a')}`",
            f"- Paper portfolios: `{paths.get('paper_portfolios', 'n/a')}`",
            f"- Hypothesis events: `{paths.get('hypothesis_events', 'n/a')}`",
            "",
            "## Safety",
            "- Paper mode only.",
            "- Real orders disabled.",
            "- Testnet orders disabled.",
            "- Telegram requested stop through safe control queue.",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
