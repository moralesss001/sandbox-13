from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .binance_data import get_exchange_info, get_latest_klines
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
from .research_session_manager import ResearchSessionManager
from .runtime_status import RuntimeStatusStore, portfolio_counts, utc_now
from .signal_adapter import signal_from_klines
from .production_like_raw_source import production_like_raw_signal_from_klines
from .universe import CONTRACT_UNIVERSE, CONTRACT_UNIVERSE_NAME


class LiveResearchEngine:
    MAX_CLOSED_CANDLE_AGE_MS = 30 * 60 * 1000

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        data_root: str | Path = "data",
        status_store: RuntimeStatusStore | None = None,
        command_queue: CommandQueue | None = None,
        session_id: str | None = None,
        session_manager: ResearchSessionManager | None = None,
    ):
        self.config = config or {}
        self.session_id = session_id
        self.session_manager = session_manager
        if self.session_id and self.session_manager is None:
            raise ValueError("session_manager is required when session_id is set")
        session_runtime_status = (
            self.session_manager.paths(self.session_id).runtime_status
            if self.session_id and self.session_manager is not None
            else None
        )
        self.storage = LivePaperStorage(data_root, runtime_status_path=session_runtime_status)
        self.data_root = self.storage.data_root
        if self.session_id:
            self.status_store = self.session_manager.session_status_store(self.session_id)
            self.global_status_store = status_store or self.session_manager.global_status_store
            queue_path = self.session_manager.data_root / "runtime/commands.jsonl"
        else:
            self.status_store = status_store or RuntimeStatusStore(self.storage.runtime_status_path)
            self.global_status_store = self.status_store
            queue_path = self.data_root / "runtime/commands.jsonl"
        self.command_queue = command_queue or CommandQueue(queue_path)
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
        closed_signal_ids = self.storage.closed_signal_ids()
        runner = HypothesisRunner(
            starting_balance_usdt=float(paper_cfg.get("starting_balance_usdt", 1000)),
            default_position_size_usdt=float(paper_cfg.get("default_position_size_usdt", 100)),
            leverage=float(paper_cfg.get("leverage", 10)),
            fee_rate=float(paper_cfg.get("fee_rate", 0.0004)),
            slippage_pct=float(paper_cfg.get("slippage_pct", 0.0005)),
            intrabar_policy=str(paper_cfg.get("intrabar_policy", "conservative")),
            data_root=self.data_root,
            known_closed_signal_ids=closed_signal_ids,
            session_id=self.session_id,
        )
        self.storage.restore_closed_trades(runner.portfolios)
        self.storage.restore_open_positions(runner.portfolios, closed_signal_ids=closed_signal_ids)
        self.storage.save_open_positions(runner.portfolios)
        self.storage.append_closed_trades([])
        status = self.status_store.read()
        global_status = self.global_status_store.read()
        is_single_service = bool(self.session_id) or global_status.get("runtime_layout") == "single_service"
        last_processed = dict(status.get("last_processed_candles") or {})
        ignored_short_candidates_count = int(status.get("ignored_short_candidates_count") or 0)
        rejected_candidates_count = int(status.get("rejected_candidates_count") or 0)
        raw_candidates_lifetime = int(
            global_status.get("lifetime_raw_candidates", global_status.get("raw_candidates_lifetime", 0)) or 0
        )
        raw_candidates_current_run = (
            int(status.get("raw_candidates_count") or 0) if self.session_id else 0
        )
        production_would_allow_count = int(status.get("production_would_allow_count") or 0)
        production_would_block_count = int(status.get("production_would_block_count") or 0)
        shadow_blocked_but_tracked_count = int(status.get("shadow_blocked_but_tracked_count") or 0)
        shadow_gate_block_counts = dict(
            status.get("shadow_gate_block_counts") or {"rsi_gate": 0, "market_mode_15m_gate": 0}
        )
        last_shadow_block_reasons = list(status.get("last_shadow_block_reasons") or [])
        symbols = [symbol.upper() for symbol in symbols]
        configured_symbols = list(symbols)
        configured_universe_name = (
            CONTRACT_UNIVERSE_NAME if tuple(configured_symbols) == CONTRACT_UNIVERSE else "explicit_runtime"
        )
        active_symbols: set[str] = set()
        unavailable_symbols: set[str] = set()
        unavailable_symbol_reasons: dict[str, str] = {}
        open_count, _ = portfolio_counts(runner.portfolios)
        closed_trades_count = self.storage.closed_trades_count()
        closed_trades_lifetime = int(
            global_status.get("lifetime_closed_trades", global_status.get("closed_trades_lifetime", 0)) or 0
        ) if self.session_id else closed_trades_count
        diagnostics = self.storage.diagnostics()
        diagnostics["paths_exist"]["runtime_status"] = True
        session_started_at = status.get("started_at") or utc_now()
        self.status_store.write(
            {
                **status,
                "mode": "sandbox_run_all" if is_single_service else "live_paper_lifecycle_mvp",
                "interface_target": "telegram",
                "cli_is_fallback": True,
                "status": "running" if self.session_id else status.get("status"),
                "session_id": self.session_id,
                "started_at": session_started_at,
                "symbols": symbols,
                "configured_universe": configured_universe_name,
                "configured_symbols": configured_symbols,
                "configured_symbols_count": len(configured_symbols),
                "active_symbols": [],
                "active_symbols_count": 0,
                "unavailable_symbols": [],
                "unavailable_symbols_count": 0,
                "unavailable_symbol_reasons": {},
                "timeframe": timeframe,
                "direction": "LONG_ONLY" if is_single_service else "LONG",
                "candidate_mode": source_metadata.candidate_source,
                **source_metadata.as_status_fields(),
                "live_direction_policy": "LONG_ONLY",
                "last_processed_candles": last_processed,
                "open_virtual_positions_count": open_count,
                "open_positions_count": open_count,
                "open_positions_current": open_count,
                "closed_trades_count": closed_trades_count,
                "closed_trades_lifetime": closed_trades_lifetime,
                "ignored_short_candidates_count": ignored_short_candidates_count,
                "rejected_candidates_count": rejected_candidates_count,
                "shadow_gates_enabled": True,
                "raw_candidates_count": raw_candidates_current_run,
                "raw_candidates_lifetime": raw_candidates_lifetime,
                "raw_candidates_current_run": raw_candidates_current_run,
                "production_would_allow_count": production_would_allow_count,
                "production_would_block_count": production_would_block_count,
                "shadow_blocked_but_tracked_count": shadow_blocked_but_tracked_count,
                "shadow_gate_block_counts": shadow_gate_block_counts,
                "last_shadow_block_reasons": last_shadow_block_reasons[-20:],
                "storage_paths": self.storage.paths(),
                **diagnostics,
                "research_pack_2_enabled": False,
                "checkpoint_progress": {
                    "closed_trades_count": closed_trades_count,
                    "next_checkpoint": self._next_checkpoint(closed_trades_count),
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
        self._sync_global_status()

        index = 0
        while run_forever or index < max(1, int(max_iterations)):
            index += 1
            control_action = self._control_action()
            if control_action in {"STOP_LIVE_RESEARCH", "RESTART_LIVE_RESEARCH"}:
                for portfolio in runner.portfolios.values():
                    for position in portfolio.open_positions:
                        position.session_final_status = "UNRESOLVED_AT_SESSION_END"
                self.storage.save_open_positions(runner.portfolios)
                paths = runner.save_artifacts()
                open_count, _ = portfolio_counts(runner.portfolios)
                closed_trades_count = self.storage.closed_trades_count()
                report_path = self._write_engine_stop_report(runner, paths, reason=control_action)
                self.status_store.update(
                    status="stopped" if self.session_id else status.get("status"),
                    ended_at=utc_now() if self.session_id else status.get("ended_at"),
                    open_virtual_positions_count=open_count,
                    open_positions_count=open_count,
                    open_positions_current=open_count,
                    closed_trades_count=closed_trades_count,
                    closed_trades_lifetime=closed_trades_lifetime,
                    raw_candidates_count=raw_candidates_current_run,
                    raw_candidates_lifetime=raw_candidates_lifetime,
                    raw_candidates_current_run=raw_candidates_current_run,
                    **self.storage.diagnostics(),
                    latest_report_path=str(report_path),
                    last_iteration_at=utc_now(),
                )
                self._sync_global_status()
                if self.session_id:
                    self.session_manager.finalize_session(
                        self.session_id,
                        stop_reason=control_action,
                        unresolved_open_positions_count=open_count,
                        latest_report_path=str(report_path),
                        active_symbols=self._ordered_symbols(configured_symbols, active_symbols),
                        unavailable_symbols=self._ordered_symbols(configured_symbols, unavailable_symbols),
                    )
                else:
                    self.global_status_store.update(
                        control_state="stopped" if control_action == "STOP_LIVE_RESEARCH" else "restart_requested"
                    )
                return {
                    "portfolios": runner.portfolios,
                    "events": runner.events,
                    "metrics": runner.metrics(),
                    "paths": {**paths, "final_stop_report": str(report_path)},
                    "signal_source": self._signal_source_name(source_metadata.candidate_source),
                    **self._candidate_result_fields(source_metadata),
                }
            try:
                exchange_info = get_exchange_info(base_url=self.public_base_url)
                exchange_symbols = self._exchange_symbols(exchange_info)
            except Exception as exc:  # noqa: BLE001 - fail closed when eligibility cannot be verified.
                for symbol in symbols:
                    self._mark_symbol_unavailable(
                        symbol,
                        "exchange_info_request_failed",
                        configured_symbols,
                        active_symbols,
                        unavailable_symbols,
                        unavailable_symbol_reasons,
                    )
                self._append_error(f"exchangeInfo: {type(exc).__name__}")
                paths = runner.save_artifacts()
                self.status_store.update(last_iteration_at=utc_now())
                self._sync_global_status()
                if run_forever or index < max(1, int(max_iterations)):
                    time.sleep(max(1, int(interval_sec)))
                continue

            for symbol in symbols:
                eligibility_reason = self._symbol_eligibility_reason(symbol, exchange_symbols)
                if eligibility_reason:
                    self._mark_symbol_unavailable(
                        symbol,
                        eligibility_reason,
                        configured_symbols,
                        active_symbols,
                        unavailable_symbols,
                        unavailable_symbol_reasons,
                    )
                    continue
                htf_klines = None
                try:
                    klines = get_latest_klines(symbol, timeframe, limit=200, base_url=self.public_base_url)
                    if candidate_source == CandidateSourceType.PRODUCTION_LIKE_RAW.value:
                        htf_klines = get_latest_klines(symbol, "1h", limit=200, base_url=self.public_base_url)
                except Exception as exc:  # noqa: BLE001 - isolate one unavailable market-data symbol.
                    self._mark_symbol_unavailable(
                        symbol,
                        "market_data_error",
                        configured_symbols,
                        active_symbols,
                        unavailable_symbols,
                        unavailable_symbol_reasons,
                    )
                    self._append_error(f"{symbol} {timeframe}: {exc}")
                    continue

                if klines.empty or (
                    candidate_source == CandidateSourceType.PRODUCTION_LIKE_RAW.value
                    and (htf_klines is None or htf_klines.empty)
                ):
                    self._mark_symbol_unavailable(
                        symbol,
                        "empty_candles",
                        configured_symbols,
                        active_symbols,
                        unavailable_symbols,
                        unavailable_symbol_reasons,
                    )
                    self._append_error(f"{symbol} {timeframe}: empty_candles")
                    continue

                try:
                    self._validate_candle_frame(klines)
                    if htf_klines is not None:
                        self._validate_candle_frame(htf_klines)
                    closed = self._latest_closed_klines(klines)
                    if closed.empty:
                        raise ValueError("No closed candle")
                    last_close_time = int(closed.iloc[-1]["close_time"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    self._mark_symbol_unavailable(
                        symbol,
                        "malformed_candles",
                        configured_symbols,
                        active_symbols,
                        unavailable_symbols,
                        unavailable_symbol_reasons,
                    )
                    self._append_error(f"{symbol} {timeframe}: malformed_candles")
                    continue

                if self._now_ms() - last_close_time > self.MAX_CLOSED_CANDLE_AGE_MS:
                    self._mark_symbol_unavailable(
                        symbol,
                        "stale_closed_candle",
                        configured_symbols,
                        active_symbols,
                        unavailable_symbols,
                        unavailable_symbol_reasons,
                    )
                    self._append_error(f"{symbol} {timeframe}: stale_closed_candle")
                    continue

                active_symbols.add(symbol)
                unavailable_symbols.discard(symbol)
                unavailable_symbol_reasons.pop(symbol, None)
                self._write_universe_availability(
                    configured_symbols,
                    active_symbols,
                    unavailable_symbols,
                    unavailable_symbol_reasons,
                )

                try:
                    self._save_live_market(symbol, timeframe, klines)
                    close_time = str(int(closed.iloc[-1].get("close_time")))
                    key = f"{symbol}:{timeframe}"
                    if last_processed.get(key) == close_time:
                        continue
                    if self.session_id and key not in last_processed:
                        last_processed[key] = close_time
                        self.status_store.update(
                            last_processed_candles=last_processed,
                            last_processed_candle_time=close_time,
                        )
                        self._sync_global_status()
                        continue
                    current_candle = closed.iloc[-1].to_dict()
                    before_closed_count = self.storage.closed_trades_count()
                    closed_trades = self._update_open_positions(runner, symbol, current_candle)
                    self.storage.append_closed_trades(closed_trades)
                    after_closed_count = self.storage.closed_trades_count()
                    closed_trades_count = after_closed_count
                    closed_trades_lifetime += max(0, after_closed_count - before_closed_count)
                    self.storage.save_open_positions(runner.portfolios)
                    signal = self._build_signal(
                        symbol,
                        timeframe,
                        closed,
                        candidate_source,
                        htf_klines=htf_klines,
                    )
                    if signal:
                        signal.session_id = self.session_id
                        raw_candidates_lifetime += 1
                        raw_candidates_current_run += 1
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
                            self._append_error(str(exc))
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
                except Exception as exc:  # noqa: BLE001 - keep other symbols running without misclassifying data.
                    self._append_error(f"{symbol} {timeframe} internal: {type(exc).__name__}")
            paths = runner.save_artifacts()
            open_count, _ = portfolio_counts(runner.portfolios)
            closed_trades_count = self.storage.closed_trades_count()
            self.status_store.update(
                last_iteration_at=utc_now(),
                last_processed_candles=last_processed,
                last_processed_candle_time=max(last_processed.values()) if last_processed else None,
                open_virtual_positions_count=open_count,
                open_positions_count=open_count,
                open_positions_current=open_count,
                closed_trades_count=closed_trades_count,
                closed_trades_lifetime=closed_trades_lifetime,
                ignored_short_candidates_count=ignored_short_candidates_count,
                rejected_candidates_count=rejected_candidates_count,
                shadow_gates_enabled=True,
                raw_candidates_count=raw_candidates_current_run,
                raw_candidates_lifetime=raw_candidates_lifetime,
                raw_candidates_current_run=raw_candidates_current_run,
                production_would_allow_count=production_would_allow_count,
                production_would_block_count=production_would_block_count,
                shadow_blocked_but_tracked_count=shadow_blocked_but_tracked_count,
                shadow_gate_block_counts=shadow_gate_block_counts,
                last_shadow_block_reasons=last_shadow_block_reasons[-20:],
                configured_symbols=configured_symbols,
                configured_symbols_count=len(configured_symbols),
                active_symbols=self._ordered_symbols(configured_symbols, active_symbols),
                active_symbols_count=len(active_symbols),
                unavailable_symbols=self._ordered_symbols(configured_symbols, unavailable_symbols),
                unavailable_symbols_count=len(unavailable_symbols),
                unavailable_symbol_reasons=dict(unavailable_symbol_reasons),
                candidate_mode=source_metadata.candidate_source,
                **source_metadata.as_status_fields(),
                live_direction_policy="LONG_ONLY",
                storage_paths=self.storage.paths(),
                **self.storage.diagnostics(),
                checkpoint_progress={
                    "closed_trades_count": closed_trades_count,
                    "next_checkpoint": self._next_checkpoint(closed_trades_count),
                },
                latest_report_path=self.status_store.read().get("latest_report_path"),
            )
            self._sync_global_status()
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

    def _write_universe_availability(
        self,
        configured_symbols: list[str],
        active_symbols: set[str],
        unavailable_symbols: set[str],
        unavailable_symbol_reasons: dict[str, str],
    ) -> None:
        self.status_store.update(
            symbols=configured_symbols,
            configured_symbols=configured_symbols,
            configured_symbols_count=len(configured_symbols),
            active_symbols=self._ordered_symbols(configured_symbols, active_symbols),
            active_symbols_count=len(active_symbols),
            unavailable_symbols=self._ordered_symbols(configured_symbols, unavailable_symbols),
            unavailable_symbols_count=len(unavailable_symbols),
            unavailable_symbol_reasons=dict(unavailable_symbol_reasons),
        )
        self._sync_global_status()

    def _mark_symbol_unavailable(
        self,
        symbol: str,
        reason: str,
        configured_symbols: list[str],
        active_symbols: set[str],
        unavailable_symbols: set[str],
        unavailable_symbol_reasons: dict[str, str],
    ) -> None:
        active_symbols.discard(symbol)
        unavailable_symbols.add(symbol)
        unavailable_symbol_reasons[symbol] = reason
        self._write_universe_availability(
            configured_symbols,
            active_symbols,
            unavailable_symbols,
            unavailable_symbol_reasons,
        )

    def _ordered_symbols(self, configured_symbols: list[str], selected: set[str]) -> list[str]:
        return [symbol for symbol in configured_symbols if symbol in selected]

    def _exchange_symbols(self, exchange_info: dict[str, Any]) -> dict[str, dict[str, Any]]:
        rows = exchange_info.get("symbols")
        if not isinstance(rows, list):
            raise ValueError("Malformed Binance exchangeInfo response")
        return {
            str(row.get("symbol", "")).upper(): row
            for row in rows
            if isinstance(row, dict) and row.get("symbol")
        }

    def _symbol_eligibility_reason(
        self,
        symbol: str,
        exchange_symbols: dict[str, dict[str, Any]],
    ) -> str | None:
        details = exchange_symbols.get(symbol.upper())
        if details is None:
            return "symbol_absent_exchange_info"
        if details.get("status") != "TRADING":
            return "symbol_status_not_trading"
        if details.get("contractType") != "PERPETUAL":
            return "symbol_not_perpetual"
        if details.get("quoteAsset") != "USDT":
            return "symbol_quote_asset_mismatch"
        return None

    def _now_ms(self) -> int:
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    def _validate_candle_frame(self, klines) -> None:
        required = {"open", "high", "low", "close", "volume", "close_time"}
        if not required.issubset(klines.columns):
            raise ValueError("Missing required candle columns")
        latest = klines.iloc[-1]
        for column in required:
            float(latest[column])

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

    def _build_signal(
        self,
        symbol: str,
        timeframe: str,
        closed,
        candidate_source: str,
        htf_klines=None,
    ):
        ensure_supported_candidate_source(candidate_source)
        if candidate_source == CandidateSourceType.SIMPLIFIED_PLACEHOLDER.value:
            return signal_from_klines(symbol, timeframe, closed)
        if candidate_source == CandidateSourceType.PRODUCTION_LIKE_RAW.value:
            return production_like_raw_signal_from_klines(
                symbol,
                timeframe,
                closed,
                htf_klines=htf_klines,
            )
        raise ValueError(f"candidate_source is not implemented for live-research: {candidate_source}")

    def _gate_outcome_analytics(self, runner: HypothesisRunner) -> dict[str, int]:
        from .gate_analytics import summarize_gate_outcomes

        trades = []
        for portfolio in runner.portfolios.values():
            trades.extend(portfolio.closed_trades)
        return summarize_gate_outcomes(trades)

    def mark_latest_report(self, report_path: str | Path) -> None:
        self.status_store.update(latest_report_path=str(report_path))
        self._sync_global_status()

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
        now_ms = self._now_ms()
        closed = klines[klines["close_time"].astype("int64") <= now_ms].copy()
        return closed

    def _control_action(self) -> str | None:
        status = self.global_status_store.read()
        processed = set(status.get("processed_command_ids") or [])
        for command in self.command_queue.read_all():
            if command.command_id in processed:
                continue
            processed.add(command.command_id)
            self.global_status_store.update(
                processed_command_ids=sorted(processed),
                last_control_command=command.command,
            )
            command_session_id = command.payload.get("session_id")
            if (
                self.session_id
                and command.command in {
                    "START_LIVE_RESEARCH",
                    "START_LIVE_PAPER",
                    "STOP_LIVE_RESEARCH",
                    "RESTART_LIVE_RESEARCH",
                }
                and command_session_id != self.session_id
            ):
                continue
            if command.command in {"STOP_LIVE_RESEARCH", "RESTART_LIVE_RESEARCH"}:
                return command.command
            if command.command in {"START_LIVE_RESEARCH", "START_LIVE_PAPER"}:
                if not self.session_id or status.get("active_session_id") == self.session_id:
                    self.global_status_store.update(control_state="running", session_status="running")
                    if self.session_id:
                        self.status_store.update(status="running")
        if (
            self.session_id
            and status.get("active_session_id") == self.session_id
            and status.get("control_state") in {"stop_requested", "restart_requested"}
        ):
            return "STOP_LIVE_RESEARCH"
        return None

    def _write_engine_stop_report(self, runner: HypothesisRunner, paths: dict[str, str], reason: str) -> Path:
        reports_dir = self.data_root / ("reports" if self.session_id else "demo_reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = reports_dir / f"engine_stop_report_{suffix}.md"
        open_count, closed_current_run = portfolio_counts(runner.portfolios)
        closed_session = self.storage.closed_trades_count()
        lines = [
            "# Crypto13Research Engine Stop Report",
            "",
            "## Summary",
            f"- Session id: {self.session_id or 'legacy_session_unscoped'}",
            f"- Reason: `{reason}`",
            f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
            f"- Open virtual positions: {open_count}",
            f"- Closed virtual trades (current run): {closed_current_run}",
            f"- Closed virtual trades (session): {closed_session}",
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
        with path.open("x", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return path

    def _append_error(self, error: str) -> None:
        self.status_store.append_error(error)
        if not self.session_id:
            return
        global_status = self.global_status_store.read()
        lifetime_errors = list(global_status.get("lifetime_errors") or [])
        lifetime_errors.append({"timestamp": utc_now(), "error": error})
        self.global_status_store.update(
            lifetime_errors=lifetime_errors[-1000:],
            errors=lifetime_errors[-20:],
        )

    def _sync_global_status(self) -> None:
        if not self.session_id:
            return
        global_status = self.global_status_store.read()
        if global_status.get("active_session_id") != self.session_id:
            return
        session_status = self.status_store.read()
        self.global_status_store.update(
            session_id=self.session_id,
            session_status=session_status.get("status"),
            session_started_at=session_status.get("started_at"),
            session_ended_at=session_status.get("ended_at"),
            raw_candidates_count=int(session_status.get("raw_candidates_count") or 0),
            raw_candidates_current_run=int(session_status.get("raw_candidates_count") or 0),
            closed_trades_count=int(session_status.get("closed_trades_count") or 0),
            open_positions_count=int(session_status.get("open_positions_count") or 0),
            open_positions_current=int(session_status.get("open_positions_count") or 0),
            production_would_allow_count=int(session_status.get("production_would_allow_count") or 0),
            production_would_block_count=int(session_status.get("production_would_block_count") or 0),
            shadow_blocked_but_tracked_count=int(
                session_status.get("shadow_blocked_but_tracked_count") or 0
            ),
            last_processed_candle_time=session_status.get("last_processed_candle_time"),
            last_processed_candles=dict(session_status.get("last_processed_candles") or {}),
            active_symbols=list(session_status.get("active_symbols") or []),
            active_symbols_count=int(session_status.get("active_symbols_count") or 0),
            unavailable_symbols=list(session_status.get("unavailable_symbols") or []),
            unavailable_symbols_count=int(session_status.get("unavailable_symbols_count") or 0),
            unavailable_symbol_reasons=dict(session_status.get("unavailable_symbol_reasons") or {}),
            latest_report_path=session_status.get("latest_report_path"),
            lifetime_raw_candidates=int(session_status.get("raw_candidates_lifetime") or 0),
            raw_candidates_lifetime=int(session_status.get("raw_candidates_lifetime") or 0),
            lifetime_closed_trades=int(session_status.get("closed_trades_lifetime") or 0),
            closed_trades_lifetime=int(session_status.get("closed_trades_lifetime") or 0),
            live_engine_enabled=session_status.get("status") == "running",
        )
