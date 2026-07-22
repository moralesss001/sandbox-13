from __future__ import annotations

import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .candidate_sources import PRODUCTION_LIKE_RAW_METADATA
from .live_paper_storage import LivePaperStorage
from .live_research_engine import LiveResearchEngine
from .research_session_manager import ResearchSessionManager
from .runtime_status import RuntimeStatusStore, utc_now
from .telegram_bot import run_telegram_bot
from .universe import CONTRACT_UNIVERSE, CONTRACT_UNIVERSE_NAME, configured_universe


DEFAULT_SYMBOLS = CONTRACT_UNIVERSE
DEFAULT_TIMEFRAME = "15m"
DEFAULT_CANDIDATE_SOURCE = "production_like_raw"
DEFAULT_INTERVAL_SEC = 60
DEFAULT_DIRECTION = "LONG_ONLY"


@dataclass(frozen=True)
class RunAllConfig:
    symbols: list[str]
    timeframe: str
    candidate_source: str
    interval_sec: int
    direction: str = DEFAULT_DIRECTION
    data_root: str = "data"
    real_orders_enabled: bool = False
    testnet_orders_enabled: bool = False
    private_api_used: bool = False


def load_run_all_config(env: Mapping[str, str] | None = None) -> RunAllConfig:
    values = env or os.environ
    symbols = configured_universe()
    interval_raw = values.get("CRYPTO13_INTERVAL_SEC", str(DEFAULT_INTERVAL_SEC))
    try:
        interval_sec = max(1, int(interval_raw))
    except ValueError:
        interval_sec = DEFAULT_INTERVAL_SEC
    return RunAllConfig(
        symbols=symbols,
        timeframe=values.get("CRYPTO13_TIMEFRAME", DEFAULT_TIMEFRAME) or DEFAULT_TIMEFRAME,
        candidate_source=values.get("CRYPTO13_CANDIDATE_SOURCE", DEFAULT_CANDIDATE_SOURCE)
        or DEFAULT_CANDIDATE_SOURCE,
        interval_sec=interval_sec,
        direction=DEFAULT_DIRECTION,
        data_root=values.get("CRYPTO13_DATA_ROOT", "data") or "data",
    )


def build_run_all_plan(config: RunAllConfig | None = None) -> dict[str, Any]:
    cfg = config or load_run_all_config()
    symbols = ",".join(cfg.symbols)
    universe_name = CONTRACT_UNIVERSE_NAME if tuple(cfg.symbols) == CONTRACT_UNIVERSE else "explicit_runtime"
    return {
        "mode": "sandbox_run_all",
        "runtime_layout": "single_service",
        "telegram_enabled": True,
        "live_engine_enabled": True,
        "symbols": cfg.symbols,
        "configured_universe": universe_name,
        "configured_symbols_count": len(cfg.symbols),
        "timeframe": cfg.timeframe,
        "candidate_source": cfg.candidate_source,
        "interval_sec": cfg.interval_sec,
        "direction": cfg.direction,
        "real_orders_enabled": cfg.real_orders_enabled,
        "testnet_orders_enabled": cfg.testnet_orders_enabled,
        "private_api_used": cfg.private_api_used,
        "telegram_command": "python -m src.main telegram-bot",
        "engine_command": (
            "python -m src.main live-research "
            f"--symbols {symbols} --tf {cfg.timeframe} --candidate-source {cfg.candidate_source} "
            f"--run-forever --interval-sec {cfg.interval_sec}"
        ),
        "railway_start_command": "python -m src.main run-all",
        "railway_pre_deploy_command": "",
    }


def write_run_all_status(
    plan: dict[str, Any],
    status_store: RuntimeStatusStore | None = None,
    session_manager: ResearchSessionManager | None = None,
) -> dict[str, Any]:
    manager = session_manager or ResearchSessionManager(
        status_store.path.parent.parent if status_store is not None else "data",
        global_status_path=status_store.path if status_store is not None else None,
    )
    store = status_store or manager.global_status_store
    previous = manager.ensure_initialized()
    safety_status = {
        **(previous.get("safety_status") or {}),
        "api_mode": "paper",
        "telegram_read_only": True,
        "public_data_only": True,
        "private_api_used": False,
        "real_orders_enabled": False,
        "testnet_orders_enabled": False,
    }
    prior_control_state = str(previous.get("control_state") or "stopped")
    if previous.get("active_session_id") and prior_control_state in {
        "shutdown_requested",
        "shutdown_complete",
    }:
        prior_control_state = "running"
    status = {
        **previous,
        "mode": plan["mode"],
        "runtime_layout": plan["runtime_layout"],
        "telegram_enabled": True,
        "live_engine_enabled": False,
        "service_started_at": previous.get("service_started_at") or utc_now(),
        "symbols": plan["symbols"],
        "configured_universe": plan["configured_universe"],
        "configured_symbols": plan["symbols"],
        "configured_symbols_count": plan["configured_symbols_count"],
        "active_symbols": [],
        "active_symbols_count": 0,
        "unavailable_symbols": [],
        "unavailable_symbols_count": 0,
        "unavailable_symbol_reasons": {},
        "timeframe": plan["timeframe"],
        "direction": plan["direction"],
        "live_direction_policy": "LONG_ONLY",
        "candidate_mode": plan["candidate_source"],
        **PRODUCTION_LIKE_RAW_METADATA.as_status_fields(),
        "control_state": "stopped" if not previous.get("active_session_id") else prior_control_state,
        "railway_start_command": plan["railway_start_command"],
        "railway_pre_deploy_command": plan["railway_pre_deploy_command"],
        "global_runtime_status_path": str(store.path),
        "sessions_root": str(manager.sessions_root),
        "runtime_data_directory": str(manager.data_root),
        "runtime_status_path": str(store.path),
        "safety_status": safety_status,
    }
    return store.write(status)


def format_run_all_plan(plan: dict[str, Any]) -> str:
    lines = [
        "Crypto13Research run-all plan",
        f"mode: {plan['mode']}",
        f"runtime_layout: {plan['runtime_layout']}",
        f"telegram_enabled: {plan['telegram_enabled']}",
        f"live_engine_enabled: {plan['live_engine_enabled']}",
        f"symbols: {', '.join(plan['symbols'])}",
        f"configured_universe: {plan['configured_universe']}",
        f"configured_symbols_count: {plan['configured_symbols_count']}",
        f"timeframe: {plan['timeframe']}",
        f"candidate_source: {plan['candidate_source']}",
        f"interval_sec: {plan['interval_sec']}",
        f"direction: {plan['direction']}",
        f"real_orders_enabled: {plan['real_orders_enabled']}",
        f"testnet_orders_enabled: {plan['testnet_orders_enabled']}",
        f"private_api_used: {plan['private_api_used']}",
        f"telegram_command: {plan['telegram_command']}",
        f"engine_command: {plan['engine_command']}",
        f"railway_start_command: {plan['railway_start_command']}",
        "railway_pre_deploy_command: <empty>",
    ]
    return "\n".join(lines)


def install_shutdown_handlers(stop_event: threading.Event, status_store: RuntimeStatusStore) -> None:
    def _handle_shutdown(signum: int, _frame: Any) -> None:
        stop_event.set()
        status_store.update(
            control_state="shutdown_requested",
            shutdown_signal=signum,
            live_engine_enabled=False,
            last_iteration_at=utc_now(),
        )

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)


def run_all(
    dry_run: bool = False,
    config: RunAllConfig | None = None,
    telegram_runner: Callable[..., None] = run_telegram_bot,
    engine_factory: Callable[..., LiveResearchEngine] = LiveResearchEngine,
    status_store: RuntimeStatusStore | None = None,
    supervisor_runtime_sec: float | None = None,
) -> int:
    cfg = config or load_run_all_config()
    plan = build_run_all_plan(cfg)
    manager = ResearchSessionManager(
        cfg.data_root,
        global_status_path=status_store.path if status_store is not None else None,
    )
    store = status_store or manager.global_status_store
    previous = manager.ensure_initialized()
    if not dry_run and previous.get("active_session_id") and previous.get("control_state") == "session_preparing":
        orphan_session_id = str(previous["active_session_id"])
        report_path = manager.write_failure_report(
            orphan_session_id,
            reason="startup_recovered_incomplete_start",
            unresolved_open_positions_count=0,
        )
        manager.finalize_session(
            orphan_session_id,
            stop_reason="startup_recovered_incomplete_start",
            unresolved_open_positions_count=0,
            latest_report_path=str(report_path),
        )
    write_run_all_status(plan, store, manager)
    print(format_run_all_plan(plan))
    if dry_run:
        return 0

    stop_event = threading.Event()
    install_shutdown_handlers(stop_event, store)

    def record_lifetime_error(error: str) -> None:
        status = store.read()
        entry = {"timestamp": utc_now(), "error": error}
        errors = [*list(status.get("errors") or []), entry][-20:]
        lifetime_errors = [*list(status.get("lifetime_errors") or []), entry][-1000:]
        store.update(errors=errors, lifetime_errors=lifetime_errors)

    def supervise_telegram() -> None:
        while not stop_event.is_set():
            try:
                telegram_runner(once=False, data_root=cfg.data_root)
            except Exception as exc:  # noqa: BLE001 - Railway supervisor must log and retry.
                record_lifetime_error(f"telegram_bot: {type(exc).__name__}")
                stop_event.wait(5)

    def supervise_engine() -> None:
        while not stop_event.is_set():
            status = store.read()
            control_state = str(status.get("control_state") or "stopped")
            session_id = status.get("active_session_id")
            if control_state not in {"start_requested", "running", "stop_requested", "restart_requested"} or not session_id:
                store.update(live_engine_enabled=False)
                stop_event.wait(5)
                continue
            try:
                store.update(live_engine_enabled=True)
                engine = engine_factory(
                    data_root=manager.paths(str(session_id)).root,
                    status_store=store,
                    session_id=str(session_id),
                    session_manager=manager,
                )
                engine.run(
                    symbols=cfg.symbols,
                    timeframe=cfg.timeframe,
                    interval_sec=cfg.interval_sec,
                    run_forever=True,
                    candidate_source=cfg.candidate_source,
                )
            except Exception as exc:  # noqa: BLE001 - keep Telegram available and log engine failures.
                record_lifetime_error(f"live_research_engine: {type(exc).__name__}")
                store.update(live_engine_enabled=False)
                if store.read().get("active_session_id") == session_id:
                    session_paths = manager.paths(str(session_id))
                    session_storage = LivePaperStorage(
                        session_paths.root,
                        runtime_status_path=session_paths.runtime_status,
                    )
                    error_text = f"live_research_engine: {type(exc).__name__}"
                    manager.session_status_store(str(session_id)).append_error(error_text)
                    unresolved_count = 0
                    failure_reason = error_text
                    try:
                        unresolved_count = session_storage.mark_open_positions_unresolved()
                    except Exception as storage_exc:  # noqa: BLE001 - finalization must survive corrupt storage.
                        storage_error = (
                            "open_positions_finalize: "
                            f"{type(storage_exc).__name__}"
                        )
                        manager.session_status_store(str(session_id)).append_error(storage_error)
                        failure_reason = f"{error_text}; {storage_error}"
                    report_path = manager.write_failure_report(
                        str(session_id),
                        reason=failure_reason,
                        unresolved_open_positions_count=unresolved_count,
                    )
                    manager.finalize_session(
                        str(session_id),
                        stop_reason=f"engine_error:{type(exc).__name__}",
                        unresolved_open_positions_count=unresolved_count,
                        latest_report_path=str(report_path),
                    )
                stop_event.wait(5)

    threads = [
        threading.Thread(target=supervise_telegram, name="crypto13-telegram", daemon=True),
        threading.Thread(target=supervise_engine, name="crypto13-live-engine", daemon=True),
    ]
    for thread in threads:
        thread.start()

    started_at = time.monotonic()
    while not stop_event.is_set():
        if supervisor_runtime_sec is not None and time.monotonic() - started_at >= supervisor_runtime_sec:
            stop_event.set()
            break
        time.sleep(1)
    for thread in threads:
        thread.join(timeout=10)
    final_status = store.read()
    store.update(
        live_engine_enabled=False,
        telegram_enabled=False,
        service_state="stopped",
        control_state=final_status.get("control_state") if final_status.get("active_session_id") else "stopped",
    )
    return 0


def main() -> None:
    raise SystemExit(run_all(dry_run="--dry-run" in sys.argv))
