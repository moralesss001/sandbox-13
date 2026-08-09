from __future__ import annotations

import errno
import subprocess
import sys
import threading
from pathlib import Path

from src.run_all import (
    DEFAULT_CANDIDATE_SOURCE,
    RunAllConfig,
    build_run_all_plan,
    install_shutdown_handlers,
    load_run_all_config,
    run_all,
    write_run_all_status,
)
from src.live_paper_storage import LivePaperStorage
from src.order_models import SignalCandidate
from src.paper_broker import PaperBroker
from src.portfolio import PaperPortfolio
from src.runtime_status import RuntimeStatusStore
from src.research_session_manager import ResearchSessionManager
from src.universe import CONTRACT_UNIVERSE


def test_run_all_defaults_are_safe_and_production_like_raw():
    config = load_run_all_config({})

    assert config.symbols == list(CONTRACT_UNIVERSE)
    assert config.timeframe == "15m"
    assert config.candidate_source == DEFAULT_CANDIDATE_SOURCE
    assert config.interval_sec == 60
    assert config.direction == "LONG_ONLY"
    assert config.real_orders_enabled is False
    assert config.testnet_orders_enabled is False
    assert config.private_api_used is False


def test_run_all_legacy_symbol_env_cannot_narrow_contract_universe():
    config = load_run_all_config(
        {
            "CRYPTO13_SYMBOLS": "solusdt, ETHUSDT",
            "CRYPTO13_TIMEFRAME": "15m",
            "CRYPTO13_CANDIDATE_SOURCE": "production_like_raw",
            "CRYPTO13_INTERVAL_SEC": "7",
        }
    )

    assert config.symbols == list(CONTRACT_UNIVERSE)
    assert config.timeframe == "15m"
    assert config.candidate_source == "production_like_raw"
    assert config.interval_sec == 7
    assert config.direction == "LONG_ONLY"


def test_run_all_plan_contains_expected_component_commands():
    plan = build_run_all_plan(RunAllConfig(symbols=["BTCUSDT"], timeframe="15m", candidate_source="production_like_raw", interval_sec=60))

    assert plan["mode"] == "sandbox_run_all"
    assert plan["runtime_layout"] == "single_service"
    assert plan["telegram_command"] == "python -m src.main telegram-bot"
    assert "--candidate-source production_like_raw" in plan["engine_command"]
    assert "--run-forever" in plan["engine_command"]
    assert plan["railway_start_command"] == "python -m src.main run-all"
    assert plan["railway_pre_deploy_command"] == ""


def test_run_all_status_metadata_is_single_service_and_safe(tmp_path):
    store = RuntimeStatusStore(tmp_path / "runtime/runtime_status.json")
    plan = build_run_all_plan()

    status = write_run_all_status(plan, store)

    assert status["mode"] == "sandbox_run_all"
    assert status["runtime_layout"] == "single_service"
    assert status["telegram_enabled"] is True
    assert status["live_engine_enabled"] is False
    assert status["candidate_source"] == "production_like_raw"
    assert status["timeframe"] == "15m"
    assert status["direction"] == "LONG_ONLY"
    assert status["configured_symbols"] == list(CONTRACT_UNIVERSE)
    assert status["configured_symbols_count"] == 46
    assert status["active_symbols"] == []
    assert status["unavailable_symbols"] == []
    assert status["safety_status"]["real_orders_enabled"] is False
    assert status["safety_status"]["testnet_orders_enabled"] is False
    assert status["safety_status"]["private_api_used"] is False


def test_run_all_dry_run_does_not_start_components(tmp_path, capsys):
    calls = {"telegram": 0, "engine": 0}

    def telegram_runner(**_kwargs):
        calls["telegram"] += 1

    class Engine:
        def __init__(self, **_kwargs):
            calls["engine"] += 1

    result = run_all(
        dry_run=True,
        telegram_runner=telegram_runner,
        engine_factory=Engine,
        status_store=RuntimeStatusStore(tmp_path / "runtime/runtime_status.json"),
    )

    output = capsys.readouterr().out
    assert result == 0
    assert calls == {"telegram": 0, "engine": 0}
    assert "railway_start_command: python -m src.main run-all" in output
    assert "railway_pre_deploy_command: <empty>" in output


def test_run_all_starts_telegram_and_live_engine_components(tmp_path):
    calls = {"telegram": 0, "engine_init": 0, "engine_run": 0}
    store = RuntimeStatusStore(tmp_path / "runtime/global_runtime_status.json")
    manager = ResearchSessionManager(tmp_path, global_status_path=store.path)
    manager.ensure_initialized()
    session_id, session_paths = manager.create_session(
        {
            "timeframe": "15m",
            "direction": "LONG_ONLY",
            "candidate_source": "production_like_raw",
            "candidate_source_version": "v2",
            "configured_symbols": list(CONTRACT_UNIVERSE),
        }
    )
    manager.mark_start_requested(session_id)
    config = RunAllConfig(
        symbols=list(CONTRACT_UNIVERSE),
        timeframe="15m",
        candidate_source="production_like_raw",
        interval_sec=1,
        data_root=str(tmp_path),
    )

    def telegram_runner(**kwargs):
        calls["telegram"] += 1
        assert kwargs["data_root"] == str(tmp_path)

    class Engine:
        def __init__(self, **_kwargs):
            calls["engine_init"] += 1
            assert _kwargs["session_id"] == session_id
            assert _kwargs["data_root"] == session_paths.root

        def run(self, **kwargs):
            calls["engine_run"] += 1
            assert kwargs["candidate_source"] == "production_like_raw"
            assert kwargs["timeframe"] == "15m"
            assert kwargs["symbols"] == list(CONTRACT_UNIVERSE)
            raise RuntimeError("engine smoke stop")

    result = run_all(
        dry_run=False,
        config=config,
        telegram_runner=telegram_runner,
        engine_factory=Engine,
        status_store=store,
        supervisor_runtime_sec=0.05,
    )

    assert result == 0
    assert calls["telegram"] >= 1
    assert calls["engine_init"] >= 1
    assert calls["engine_run"] >= 1
    manifest = __import__("json").loads(session_paths.manifest.read_text(encoding="utf-8"))
    assert manifest["status"] == "stopped"
    assert manifest["stop_reason"] == "engine_error:RuntimeError"
    assert manifest["latest_report_path"]
    assert Path(manifest["latest_report_path"]).exists()
    session_status = manager.session_status_store(session_id).read()
    assert session_status["errors"]


def test_run_all_uses_same_custom_data_root_for_telegram_engine_and_status(tmp_path):
    calls = {"telegram_roots": [], "engine_roots": []}
    config = RunAllConfig(
        symbols=["BTCUSDT"],
        timeframe="15m",
        candidate_source="production_like_raw",
        interval_sec=1,
        data_root=str(tmp_path),
    )
    store = RuntimeStatusStore(tmp_path / "runtime/runtime_status.json")
    manager = ResearchSessionManager(tmp_path, global_status_path=store.path)
    manager.ensure_initialized()
    session_id, session_paths = manager.create_session(
        {
            "timeframe": "15m",
            "direction": "LONG_ONLY",
            "candidate_source": "production_like_raw",
            "candidate_source_version": "v2",
            "configured_symbols": ["BTCUSDT"],
        }
    )
    manager.mark_start_requested(session_id)

    def telegram_runner(**kwargs):
        calls["telegram_roots"].append(kwargs["data_root"])

    class Engine:
        def __init__(self, **kwargs):
            calls["engine_roots"].append(kwargs["data_root"])

        def run(self, **_kwargs):
            store.update(control_state="stopped")

    result = run_all(
        config=config,
        telegram_runner=telegram_runner,
        engine_factory=Engine,
        status_store=store,
        supervisor_runtime_sec=0.05,
    )

    assert result == 0
    assert set(calls["telegram_roots"]) == {str(tmp_path)}
    assert calls["engine_roots"] == [session_paths.root]
    assert Path(store.read()["runtime_data_directory"]) == tmp_path.resolve()


def test_run_all_finalizes_session_when_open_positions_storage_is_corrupt(tmp_path):
    store = RuntimeStatusStore(tmp_path / "runtime/global_runtime_status.json")
    manager = ResearchSessionManager(tmp_path, global_status_path=store.path)
    manager.ensure_initialized()
    session_id, session_paths = manager.create_session(
        {
            "timeframe": "15m",
            "direction": "LONG_ONLY",
            "candidate_source": "production_like_raw",
            "candidate_source_version": "v2",
            "configured_symbols": ["BTCUSDT"],
        }
    )
    manager.mark_start_requested(session_id)
    session_paths.open_positions.parent.mkdir(parents=True, exist_ok=True)
    session_paths.open_positions.write_text("{broken", encoding="utf-8")

    class Engine:
        def __init__(self, **_kwargs):
            pass

        def run(self, **_kwargs):
            raise RuntimeError("engine failure")

    result = run_all(
        config=RunAllConfig(
            symbols=["BTCUSDT"],
            timeframe="15m",
            candidate_source="production_like_raw",
            interval_sec=1,
            data_root=str(tmp_path),
        ),
        telegram_runner=lambda **_kwargs: None,
        engine_factory=Engine,
        status_store=store,
        supervisor_runtime_sec=0.05,
    )

    manifest = __import__("json").loads(session_paths.manifest.read_text(encoding="utf-8"))
    session_status = manager.session_status_store(session_id).read()
    assert result == 0
    assert manifest["status"] == "stopped"
    assert manifest["stop_reason"] == "engine_error:RuntimeError"
    assert any("open_positions_finalize: RuntimeError" in str(item) for item in session_status["errors"])


def test_run_all_enospc_is_terminal_even_when_report_and_atomic_finalize_fail(monkeypatch, tmp_path):
    store = RuntimeStatusStore(tmp_path / "runtime/global_runtime_status.json")
    manager = ResearchSessionManager(tmp_path, global_status_path=store.path)
    manager.ensure_initialized()
    session_id, session_paths = manager.create_session(
        {
            "timeframe": "15m",
            "direction": "LONG_ONLY",
            "candidate_source": "production_like_raw",
            "candidate_source_version": "v2",
            "configured_symbols": ["BTCUSDT"],
        }
    )
    manager.mark_start_requested(session_id)
    session_storage = LivePaperStorage(session_paths.root)
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio)
    broker.open_position(
        SignalCandidate(
            symbol="BTCUSDT",
            timeframe="15m",
            direction="LONG",
            entry=100.0,
            tp=105.0,
            sl=95.0,
            session_id=session_id,
            created_at="2026-08-09T00:00:00+00:00",
        )
    )
    session_storage.save_open_positions({"baseline_rr15": portfolio})
    closed = broker.update_positions({"high": 106.0, "low": 99.0})
    session_storage.append_closed_trades(closed)
    engine_runs = 0
    telegram_runs = 0

    class Engine:
        def __init__(self, **_kwargs):
            pass

        def run(self, **_kwargs):
            nonlocal engine_runs
            engine_runs += 1
            raise OSError(errno.ENOSPC, "No space left on device")

    def telegram_runner(**_kwargs):
        nonlocal telegram_runs
        telegram_runs += 1

    def fail_write(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(ResearchSessionManager, "write_failure_report", fail_write)
    monkeypatch.setattr(ResearchSessionManager, "finalize_session", fail_write)

    result = run_all(
        config=RunAllConfig(
            symbols=["BTCUSDT"],
            timeframe="15m",
            candidate_source="production_like_raw",
            interval_sec=1,
            data_root=str(tmp_path),
        ),
        telegram_runner=telegram_runner,
        engine_factory=Engine,
        status_store=store,
        supervisor_runtime_sec=0.05,
    )

    manifest = __import__("json").loads(session_paths.manifest.read_text(encoding="utf-8"))
    index = __import__("json").loads(manager.index_path.read_text(encoding="utf-8"))
    index_entry = next(item for item in index["sessions"] if item.get("session_id") == session_id)
    session_status = manager.session_status_store(session_id).read()
    global_status = store.read()
    assert result == 0
    assert engine_runs == 1
    assert telegram_runs >= 1
    assert session_status["status"] == "stopped"
    assert "errno=28" in session_status["terminal_error"]
    assert manifest["status"] == "stopped"
    assert manifest["stop_reason"] == "engine_error:OSError"
    assert manifest["unresolved_open_positions_count"] == 0
    assert index_entry["status"] == "stopped"
    assert index_entry["stop_reason"] == "engine_error:OSError"
    assert session_storage.load_open_positions() == []
    assert session_storage.closed_trades_count() == 1
    assert global_status["control_state"] == "stopped"
    assert global_status["active_session_id"] is None
    assert global_status["last_session_id"] == session_id
    assert global_status["live_engine_enabled"] is False


def test_run_all_shutdown_handler_updates_status(tmp_path):
    store = RuntimeStatusStore(tmp_path / "runtime/runtime_status.json")
    stop_event = threading.Event()

    install_shutdown_handlers(stop_event, store)
    handler = __import__("signal").getsignal(__import__("signal").SIGTERM)
    handler(15, None)

    status = store.read()
    assert stop_event.is_set()
    assert status["control_state"] == "shutdown_requested"
    assert status["live_engine_enabled"] is False


def test_run_all_recovers_orphaned_preparing_session_without_starting_engine(tmp_path):
    store = RuntimeStatusStore(tmp_path / "runtime/global_runtime_status.json")
    manager = ResearchSessionManager(tmp_path, global_status_path=store.path)
    manager.ensure_initialized()
    session_id, paths = manager.create_session(
        {
            "timeframe": "15m",
            "direction": "LONG_ONLY",
            "candidate_source": "production_like_raw",
            "candidate_source_version": "v2",
            "configured_symbols": ["BTCUSDT"],
        }
    )
    calls = {"engine": 0}

    class Engine:
        def __init__(self, **_kwargs):
            calls["engine"] += 1

    result = run_all(
        dry_run=False,
        config=RunAllConfig(
            symbols=["BTCUSDT"],
            timeframe="15m",
            candidate_source="production_like_raw",
            interval_sec=1,
            data_root=str(tmp_path),
        ),
        engine_factory=Engine,
        status_store=store,
        supervisor_runtime_sec=0,
    )

    manifest = __import__("json").loads(paths.manifest.read_text(encoding="utf-8"))
    assert result == 0
    assert calls["engine"] == 0
    assert manifest["status"] == "stopped"
    assert manifest["stop_reason"] == "startup_recovered_incomplete_start"
    assert manager.global_status_store.read()["active_session_id"] is None


def test_cli_help_includes_run_all():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "run-all" in result.stdout


def test_cli_run_all_help_works():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "run-all", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--dry-run" in result.stdout


def test_docs_use_railway_single_service_run_all():
    docs = [
        Path("README.md"),
        Path("deployment/sandbox_live_paper/RUNBOOK.md"),
        Path("deployment/sandbox_live_paper/START_ENGINE.md"),
        Path("deployment/sandbox_live_paper/START_TELEGRAM.md"),
        Path("deployment/sandbox_live_paper/DEPLOY_READINESS_CHECKLIST.md"),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in docs)

    assert "Railway Start Command" in text
    assert "python -m src.main run-all" in text
    assert "Pre-deploy Command: empty" in text
    assert "telegram-bot" in text
    assert "Pre-deploy Command: python -m src.main telegram-bot" not in text
