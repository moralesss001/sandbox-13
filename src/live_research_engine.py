from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .binance_data import get_latest_klines
from .candidate_sources import (
    CandidateSourceType,
    SIMPLIFIED_PLACEHOLDER_METADATA,
    ensure_supported_candidate_source,
    metadata_for_candidate_source,
)
from .command_queue import CommandQueue
from .execution_safety import validate_api_mode
from .hypothesis_runner import HypothesisRunner
from .live_paper_storage import LivePaperStorage
from .runtime_status import RuntimeStatusStore, portfolio_counts, utc_now
from .signal_adapter import signal_from_klines
from .production_like_raw_source import production_like_raw_signal_from_klines


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
        self.storage = LivePaperStorage(self.data_root)
        self.status_store = status_store or RuntimeStatusStore(self.storage.runtime_status_path)
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
        candidate_source: str = CandidateSourceType.SIMPLIFIED_PLACEHOLDER.value,
    ) -> dict[str, Any]:
        if timeframe != "15m":
            raise ValueError("Live Paper Lifecycle MVP supports 15m timeframe only.")
        source_metadata = self._live_source_metadata(candidate_source)
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
        self.storage.restore_open_positions(runner.portfolios)
        self.storage.save_open_positions(runner.portfolios)
        self.storage.append_closed_trades([])
        status = self.status_store.read()
        is_single_service = status.get("runtime_layout") == "single_service"
        last_processed = dict(status.get("last_processed_candles") or {})
        ignored_short_candidates_count = int(status.get("ignored_short_candidates_count") or 0)
        rejected_candidates_count = int(status.get("rejected_candidates_count") or 0)
        raw_candidates_count = int(status.get("raw_candidates_count") or 0)
        production_would_allow_count = int(status.get("production_would_allow_count") or 0)
        production_would_block_count = int(status.get("production_would_block_count") or 0)
        shadow_blocked_but_tracked_count = int(status.get("shadow_blocked_but_tracked_count") or 0)
        shadow_gate_block_counts = dict(
            status.get("shadow_gate_block_counts") or {"rsi_gate": 0, "market_mode_15m_gate": 0}
        )
        last_shadow_block_reasons = list(status.get("last_shadow_block_reasons") or [])
        symbols = [symbol.upper() for symbol in symbols]
        open_count, _ = portfolio_counts(runner.portfolios)
        closed_count = self.storage.closed_trades_count()
        self.status_store.write(
            {
                **status,
                "mode": "sandbox_run_all" if is_single_service else "live_paper_lifecycle_mvp",
                "interface_target": "telegram",
                "cli_is_fallback": True,
                "started_at": status.get("started_at") or utc_now(),
                "symbols": symbols,
                "timeframe": timeframe,
                "direction": "LONG_ONLY" if is_single_service else "LONG",
                "candidate_mode": source_metadata.candidate_source,
                **source_metadata.as_status_fields(),
                "live_direction_policy": "LONG_ONLY",
                "last_processed_candles": last_processed,
                "open_virtual_positions_count": open_count,
                "open_positions_count": open_count,
                "closed_trades_count": closed_count,
                "ignored_short_candidates_count": ignored_short_candidates_count,
                "rejected_candidates_count": rejected_candidates_count,
                "shadow_gates_enabled": True,
                "raw_candidates_count": raw_candidates_count,
                "production_would_allow_count": production_would_allow_count,
                "production_would_block_count": production_would_block_count,
                "shadow_blocked_but_tracked_count": shadow_blocked_but_tracked_count,
                "shadow_gate_block_counts": shadow_gate_block_counts,
                "last_shadow_block_reasons": last_shadow_block_reasons[-20:],
                "storage_paths": self.storage.paths(),
                "research_pack_2_enabled": False,
                "checkpoint_progress": {
                    "closed_trades_count": closed_count,
                    "next_checkpoint": self._next_checkpoint(closed_count),
                },
                "safety_status": {
                    "api_mode": self.api_mode,
                    "allow_real_orders": bool(self.config.get("safety", {}).get("allow_real_orders", False)),
                    "allow_testnet_orders": bool(self.config.get("safety", {}).get("allow_testnet_orders", False)),
                    "telegram_read_only": True,
                    "public_data_only": True,
                    "private_api_used": False,
                    "real_orders_enabled": False,
                    "testnet_orders_enabled": False,
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
                    "signal_source": self._signal_source_name(source_metadata.candidate_source),
                    **self._candidate_result_fields(source_metadata),
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
                    current_candle = closed.iloc[-1].to_dict()
                    closed_trades = self._update_open_positions(runner, symbol, current_candle)
                    self.storage.append_closed_trades(closed_trades)
                    self.storage.save_open_positions(runner.portfolios)
                    signal = self._build_signal(symbol, timeframe, closed, candidate_source)
                    if signal:
                        raw_candidates_count += 1
                        if signal.production_would_allow:
                            production_would_allow_count += 1
                        else:
                            production_would_block_count += 1
                            last_shadow_block_reasons.extend(signal.production_block_reasons)
                            for gate in signal.shadow_gates:
                                if gate.get("would_block"):
                                    name = str(gate.get("gate_name"))
                                    shadow_gate_block_counts[name] = int(shadow_gate_block_counts.get(name, 0)) + 1
                        try:
                            ensure_supported_candidate_source(signal.candidate_source)
                        except ValueError as exc:
                            rejected_candidates_count += 1
                            self.status_store.append_error(str(exc))
                            self.status_store.update(last_rejected_candidate_reason=str(exc))
                            last_processed[key] = close_time
                            continue
                        if signal.direction.upper() != "LONG":
                            ignored_short_candidates_count += 1
                            rejected_candidates_count += 1
                            self.status_store.update(last_rejected_candidate_reason="short_disabled_live_paper_mvp")
                        else:
                            if not signal.production_would_allow:
                                shadow_blocked_but_tracked_count += 1
                            runner.process_signal(signal, close_from_history=False)
                            self.storage.save_open_positions(runner.portfolios)
                    last_processed[key] = close_time
                except Exception as exc:  # noqa: BLE001 - status file should capture transient API errors.
                    self.status_store.append_error(f"{symbol} {timeframe}: {exc}")
            paths = runner.save_artifacts()
            open_count, _ = portfolio_counts(runner.portfolios)
            closed_count = self.storage.closed_trades_count()
            self.status_store.update(
                last_iteration_at=utc_now(),
                last_processed_candles=last_processed,
                last_processed_candle_time=max(last_processed.values()) if last_processed else None,
                open_virtual_positions_count=open_count,
                open_positions_count=open_count,
                closed_trades_count=closed_count,
                ignored_short_candidates_count=ignored_short_candidates_count,
                rejected_candidates_count=rejected_candidates_count,
                shadow_gates_enabled=True,
                raw_candidates_count=raw_candidates_count,
                production_would_allow_count=production_would_allow_count,
                production_would_block_count=production_would_block_count,
                shadow_blocked_but_tracked_count=shadow_blocked_but_tracked_count,
                shadow_gate_block_counts=shadow_gate_block_counts,
                last_shadow_block_reasons=last_shadow_block_reasons[-20:],
                candidate_mode=source_metadata.candidate_source,
                **source_metadata.as_status_fields(),
                live_direction_policy="LONG_ONLY",
                storage_paths=self.storage.paths(),
                checkpoint_progress={
                    "closed_trades_count": closed_count,
                    "next_checkpoint": self._next_checkpoint(closed_count),
                },
                latest_report_path=self.status_store.read().get("latest_report_path"),
            )
            if run_forever or index < max(1, int(max_iterations)):
                time.sleep(max(1, int(interval_sec)))
        return {
            "portfolios": runner.portfolios,
            "events": runner.events,
            "metrics": runner.metrics(),
            "paths": paths,
            "signal_source": self._signal_source_name(source_metadata.candidate_source),
            "gate_outcome_analytics": self._gate_outcome_analytics(runner),
            **self._candidate_result_fields(source_metadata),
        }

    def _update_open_positions(self, runner: HypothesisRunner, symbol: str, candle: dict[str, Any]) -> list:
        closed_trades = []
        for broker in runner.brokers.values():
            closed_trades.extend(broker.update_positions(candle, symbol=symbol))
        return closed_trades

    def _next_checkpoint(self, closed_trades_count: int) -> int:
        return ((int(closed_trades_count) // 30) + 1) * 30

    def _candidate_result_fields(self, source_metadata=SIMPLIFIED_PLACEHOLDER_METADATA) -> dict[str, Any]:
        return {
            **source_metadata.as_status_fields(),
            "candidate_mode": source_metadata.candidate_source,
            "live_direction_policy": "LONG_ONLY",
            "shadow_gates_enabled": True,
        }

    def _signal_source_name(self, candidate_source: str) -> str:
        if candidate_source == CandidateSourceType.PRODUCTION_LIKE_RAW.value:
            return "production_like_raw_live"
        return "research_simplified_live"

    def _live_source_metadata(self, candidate_source: str):
        metadata = metadata_for_candidate_source(candidate_source)
        if metadata.candidate_source not in {
            CandidateSourceType.SIMPLIFIED_PLACEHOLDER.value,
            CandidateSourceType.PRODUCTION_LIKE_RAW.value,
        }:
            raise ValueError(f"candidate_source is not implemented for live-research: {candidate_source}")
        return metadata

    def _build_signal(self, symbol: str, timeframe: str, closed, candidate_source: str):
        ensure_supported_candidate_source(candidate_source)
        if candidate_source == CandidateSourceType.SIMPLIFIED_PLACEHOLDER.value:
            return signal_from_klines(symbol, timeframe, closed)
        if candidate_source == CandidateSourceType.PRODUCTION_LIKE_RAW.value:
            return production_like_raw_signal_from_klines(symbol, timeframe, closed)
        raise ValueError(f"candidate_source is not implemented for live-research: {candidate_source}")

    def _gate_outcome_analytics(self, runner: HypothesisRunner) -> dict[str, int]:
        from .gate_analytics import summarize_gate_outcomes

        trades = []
        for portfolio in runner.portfolios.values():
            trades.extend(portfolio.closed_trades)
        return summarize_gate_outcomes(trades)

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
            if command.command in {"START_LIVE_RESEARCH", "START_LIVE_PAPER"}:
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
