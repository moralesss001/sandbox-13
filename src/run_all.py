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
from .live_research_engine import LiveResearchEngine
from .runtime_status import RuntimeStatusStore, utc_now
from .telegram_bot import run_telegram_bot


DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
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
    symbols = [
        symbol.strip().upper()
        for symbol in values.get("CRYPTO13_SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",")
        if symbol.strip()
    ]
    if not symbols:
        symbols = list(DEFAULT_SYMBOLS)
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
    return {
        "mode": "sandbox_run_all",
        "runtime_layout": "single_service",
        "telegram_enabled": True,
        "live_engine_enabled": True,
        "symbols": cfg.symbols,
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
) -> dict[str, Any]:
    store = status_store or RuntimeStatusStore(Path("data/runtime/runtime_status.json"))
    previous = store.read()
    safety_status = {
        **(previous.get("safety_status") or {}),
        "api_mode": "paper",
        "telegram_read_only": True,
        "public_data_only": True,
        "private_api_used": False,
        "real_orders_enabled": False,
        "testnet_orders_enabled": False,
    }
    status = {
        **previous,
        "mode": plan["mode"],
        "runtime_layout": plan["runtime_layout"],
        "telegram_enabled": True,
        "live_engine_enabled": True,
        "started_at": previous.get("started_at") or utc_now(),
        "symbols": plan["symbols"],
        "timeframe": plan["timeframe"],
        "direction": plan["direction"],
        "live_direction_policy": "LONG_ONLY",
        "candidate_mode": plan["candidate_source"],
        **PRODUCTION_LIKE_RAW_METADATA.as_status_fields(),
        "control_state": "running",
        "railway_start_command": plan["railway_start_command"],
        "railway_pre_deploy_command": plan["railway_pre_deploy_command"],
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
    store = status_store or RuntimeStatusStore(Path(cfg.data_root) / "runtime/runtime_status.json")
    write_run_all_status(plan, store)
    print(format_run_all_plan(plan))
    if dry_run:
        return 0

    stop_event = threading.Event()
    install_shutdown_handlers(stop_event, store)

    def supervise_telegram() -> None:
        while not stop_event.is_set():
            try:
                telegram_runner(once=False)
            except Exception as exc:  # noqa: BLE001 - Railway supervisor must log and retry.
                store.append_error(f"telegram_bot: {exc}")
                stop_event.wait(5)

    def supervise_engine() -> None:
        while not stop_event.is_set():
            status = store.read()
            control_state = str(status.get("control_state") or "running")
            if control_state in {"stopped", "stop_requested"}:
                store.update(live_engine_enabled=False)
                stop_event.wait(5)
                continue
            try:
                store.update(live_engine_enabled=True)
                engine = engine_factory(data_root=cfg.data_root, status_store=store)
                engine.run(
                    symbols=cfg.symbols,
                    timeframe=cfg.timeframe,
                    interval_sec=cfg.interval_sec,
                    run_forever=True,
                    candidate_source=cfg.candidate_source,
                )
            except Exception as exc:  # noqa: BLE001 - keep Telegram available and log engine failures.
                store.append_error(f"live_research_engine: {exc}")
                store.update(live_engine_enabled=False)
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
    store.update(live_engine_enabled=False, telegram_enabled=False, control_state="shutdown_complete")
    return 0


def main() -> None:
    raise SystemExit(run_all(dry_run="--dry-run" in sys.argv))
