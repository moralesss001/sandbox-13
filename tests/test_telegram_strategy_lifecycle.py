import json
import socket
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from src import strategy_packages as sp
from src.telegram_bot import TelegramBot
from src.telegram_buttons import TelegramResponse
from src.telegram_config import TelegramConfig
from src.telegram_handlers import TelegramHandlers
from src.telegram_strategy_lifecycle import StrategyService
from src.strategy_dashboard import journal_metrics, sandbox_counts
from src.live_paper_storage import ShadowJournal


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real network and subprocess calls are forbidden")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def eventually(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "Timed out waiting for lifecycle state"


class FakeRuntimes:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = []
        self.paths = []
        self.threads = []
        self.gates = {}
        self.fail = set()
        self.active = 0
        self.peak = 0

    def release(self, strategy_id):
        with self.lock:
            self.gates.setdefault(strategy_id, threading.Event()).set()

    def __call__(self, package, path, should_stop):
        owner = self
        key = (package["strategy_id"], package["version"])

        class Runtime:
            def run(self):
                with owner.lock:
                    gate = owner.gates.setdefault(key[0], threading.Event())
                    owner.started.append(key)
                    owner.paths.append(Path(path))
                    owner.threads.append(threading.current_thread())
                    owner.active += 1
                    owner.peak = max(owner.peak, owner.active)
                try:
                    while not should_stop() and not gate.wait(0.005):
                        pass
                    if key[0] in owner.fail:
                        raise RuntimeError("Synthetic runtime failure")
                    return {"fixture_strategy": key[0], "positions": {}}
                finally:
                    with owner.lock:
                        owner.active -= 1

        return Runtime()


@pytest.fixture
def harness(tmp_path):
    runtimes = FakeRuntimes()
    service = StrategyService(tmp_path / "strategies", runtime_factory=runtimes,
                              max_concurrent_strategies=2)
    try:
        yield service, runtimes
    finally:
        service.close(timeout=10)
        assert not service.thread.is_alive()
        assert runtimes.active == 0
        assert all(not thread.is_alive() for thread in runtimes.threads)


def raw_package(sid="alpha", version="1"):
    deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    return json.dumps(sp.example_package(sid, version, deadline)).encode()


def raw_synthetic_package(sid="diagnostic", version="1", deadline=None):
    deadline = deadline or (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    return json.dumps(sp.synthetic_package(sid, version, deadline)).encode()


def packages(service):
    with closing(sp.PackageStore(service.root / "packages.sqlite3")) as store:
        return store.list_packages()


def sessions(service):
    path = service.root / "runtime" / "lifecycle.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM sessions ORDER BY seq")]


def state(service, sid):
    return next((row["state"] for row in sessions(service)
                 if row["strategy_id"] == sid), None)


def command(service, action, sid="alpha", version="1"):
    response = service.command(f"/strategy_{action} {sid} {version}")
    assert isinstance(response, TelegramResponse)
    return response


def ready(service, sid="alpha", version="1"):
    assert isinstance(service.upload(raw_package(sid, version)), TelegramResponse)
    command(service, "approve", sid, version)


def test_upload_validates_but_only_explicit_approval_allows_run(harness):
    service, runtimes = harness
    response = service.upload(raw_package())
    assert isinstance(response, TelegramResponse)
    assert packages(service)[0]["status"] == "validated"
    assert sessions(service) == []
    command(service, "run")
    assert sessions(service) == []
    assert runtimes.started == []
    command(service, "approve")
    assert packages(service)[0]["status"] == "approved"
    assert sessions(service) == []
    assert runtimes.started == []
    command(service, "run")
    eventually(lambda: runtimes.started == [("alpha", "1")])
    assert "running" in command(service, "status").text.lower()


def test_rejected_package_cannot_run_or_be_reapproved(harness):
    service, runtimes = harness
    service.upload(raw_package())
    command(service, "reject")
    command(service, "approve")
    command(service, "run")
    assert packages(service)[0]["status"] == "rejected"
    assert sessions(service) == []
    assert runtimes.started == []


def test_multi_package_fifo_and_independent_runtime_directories(harness):
    service, runtimes = harness
    for sid in ["alpha", "beta", "gamma", "delta"]:
        ready(service, sid)
        command(service, "run", sid)
    eventually(lambda: len(runtimes.started) == 2)
    assert set(runtimes.started) == {("alpha", "1"), ("beta", "1")}
    assert state(service, "gamma") == state(service, "delta") == "queued"
    listing = service.command("/strategies")
    assert isinstance(listing, TelegramResponse)
    assert all(sid in listing.text for sid in ["alpha", "beta", "gamma", "delta"])
    runtimes.release("beta")
    eventually(lambda: ("gamma", "1") in runtimes.started)
    assert ("delta", "1") not in runtimes.started
    runtimes.release("alpha")
    eventually(lambda: ("delta", "1") in runtimes.started)
    assert runtimes.peak == 2
    assert len(set(runtimes.paths)) == 4
    expected = service.root / "runtime" / "sessions"
    assert all(path.parent == expected for path in runtimes.paths)
    assert {p.name for p in runtimes.paths} == {row["session_id"] for row in sessions(service)}


@pytest.mark.parametrize("action, terminal", [("stop", "stopped"), ("failure", "failed")])
def test_worker_stop_or_failure_does_not_stop_peer(harness, action, terminal):
    service, runtimes = harness
    for sid in ["alpha", "beta", "gamma"]:
        ready(service, sid)
        command(service, "run", sid)
    eventually(lambda: len(runtimes.started) == 2)
    if action == "failure":
        runtimes.fail.add("alpha")
        runtimes.release("alpha")
    else:
        command(service, "stop")
    eventually(lambda: state(service, "alpha") == terminal)
    eventually(lambda: ("gamma", "1") in runtimes.started)
    assert state(service, "beta") == "running"
    assert runtimes.peak == 2
    eventually(lambda: bool(command(service, "report").documents))
    report = command(service, "report")
    data = json.loads(Path(report.documents[0]).read_text())
    assert data["lifecycle_state"] == terminal
    if action == "failure":
        assert data["error_type"] == "RuntimeError"


def test_stop_queued_package_never_starts_it(harness):
    service, runtimes = harness
    for sid in ["alpha", "beta", "gamma"]:
        ready(service, sid)
        command(service, "run", sid)
    eventually(lambda: len(runtimes.started) == 2)
    command(service, "stop", "gamma")
    eventually(lambda: state(service, "gamma") == "stopped")
    runtimes.release("alpha")
    eventually(lambda: state(service, "alpha") == "completed")
    assert ("gamma", "1") not in runtimes.started


def test_repeated_run_is_idempotent_and_versions_are_independent(harness):
    service, runtimes = harness
    ready(service)
    ready(service, version="2")
    for _ in range(3):
        command(service, "run")
    command(service, "run", version="2")
    eventually(lambda: len(runtimes.started) == 2)
    before = [(row["session_id"], row["version"]) for row in sessions(service)]
    assert len(before) == 2
    assert set(runtimes.started) == {("alpha", "1"), ("alpha", "2")}
    runtimes.release("alpha")
    eventually(lambda: all(row["state"] == "completed" for row in sessions(service)))
    command(service, "run")
    assert [(row["session_id"], row["version"]) for row in sessions(service)] == before
    assert len(runtimes.started) == 2


def test_duplicate_upload_does_not_replace_approved_snapshot(harness):
    service, _ = harness
    ready(service)
    before = packages(service)
    replacement = json.loads(raw_package())
    replacement["safety_limits"]["real_orders"] = True
    assert isinstance(service.upload(json.dumps(replacement)), TelegramResponse)
    assert packages(service) == before


def test_synthetic_contract_is_separate_and_fail_closed():
    package = json.loads(raw_synthetic_package())
    assert sp.validate_package(json.dumps(package))["adapter"] == sp.SYNTHETIC_ADAPTER
    assert package["universe"] == []
    assert package["execution_model"] == {
        "name": "SYNTHETIC_NOOP",
        "market_data": False,
        "fills": False,
        "positions": False,
        "orders": False,
        "private_api": False,
    }
    for field, value in [("max_open_positions", 1), ("max_total_notional_usdt", "100")]:
        unsafe = json.loads(raw_synthetic_package())
        unsafe["safety_limits"][field] = value
        with pytest.raises(sp.PackageError, match="forbids positions and notional"):
            sp.validate_package(json.dumps(unsafe))
    unsafe = json.loads(raw_synthetic_package())
    unsafe["safety_limits"]["real_orders"] = True
    with pytest.raises(sp.PackageError, match="Unsafe execution flag"):
        sp.validate_package(json.dumps(unsafe))
    unknown = json.loads(raw_synthetic_package())
    unknown["adapter"] = "untrusted_future_adapter"
    with pytest.raises(sp.PackageError, match="not allowlisted"):
        sp.validate_package(json.dumps(unknown))
    assert sp.validate_package(raw_package())["adapter"] == sp.ADAPTER


def test_synthetic_runtime_is_durable_idempotent_and_creates_no_shadow_ledger(tmp_path):
    root = tmp_path / "strategies"
    service = StrategyService(root)
    try:
        raw = raw_synthetic_package()
        assert "validated" in service.upload(raw).text
        assert "validated" in service.upload(raw).text
        command(service, "approve", "diagnostic")
        first = command(service, "run", "diagnostic")
        second = command(service, "run", "diagnostic")
        eventually(lambda: state(service, "diagnostic") == "running")
        assert first.text.split("session=")[1].split(".")[0] == second.text.split("session=")[1].split(".")[0]
        assert len(sessions(service)) == 1
        session_path = root / "runtime" / "sessions" / sessions(service)[0]["session_id"]
        eventually(lambda: (session_path / "runtime_status.json").is_file())
        assert not (session_path / "shadow.sqlite3").exists()
        service.close(timeout=10)
        assert state(service, "diagnostic") == "paused"
    finally:
        service.close(timeout=10)

    resumed = StrategyService(root, stopped_startup=True)
    try:
        assert "startup_held=True" in command(resumed, "status", "diagnostic").text
        command(resumed, "run", "diagnostic")
        eventually(lambda: state(resumed, "diagnostic") == "running")
        eventually(lambda: json.loads((session_path / "runtime_status.json").read_text())
                   ["runtime_state"] == "running")
        command(resumed, "stop", "diagnostic")
        eventually(lambda: state(resumed, "diagnostic") == "stopped")
        eventually(lambda: bool(command(resumed, "report", "diagnostic").documents))
        response = command(resumed, "report", "diagnostic")
        report = json.loads(Path(response.documents[0]).read_text())
        assert report["adapter"] == sp.SYNTHETIC_ADAPTER
        assert report["exit_reason"] == "cooperative_stop"
        for field in ["market_data_reads", "signals", "fills", "positions", "orders", "private_api_calls"]:
            assert report[field] == 0
        assert report["preserved_ledger"] == {"journal_exists": False, "positions": {}, "closed": {}}
        assert not (session_path / "shadow.sqlite3").exists()
        before = sessions(resumed)
        command(resumed, "run", "diagnostic")
        time.sleep(0.2)
        assert sessions(resumed) == before
    finally:
        resumed.close(timeout=10)


def test_synthetic_runtime_expires_without_execution_or_shadow_ledger(tmp_path):
    root = tmp_path / "strategies"
    end = datetime.now(timezone.utc) + timedelta(seconds=2)
    service = StrategyService(root)
    try:
        service.upload(raw_synthetic_package("deadline-noop", deadline=end.isoformat()))
        command(service, "approve", "deadline-noop")
        command(service, "run", "deadline-noop")
        eventually(lambda: state(service, "deadline-noop") == "running")
        eventually(lambda: state(service, "deadline-noop") == "expired")
        row = sessions(service)[0]
        session_path = root / "runtime" / "sessions" / row["session_id"]
        eventually(lambda: bool(command(service, "report", "deadline-noop").documents))
        report = json.loads(Path(command(service, "report", "deadline-noop").documents[0]).read_text())
        assert report["exit_reason"] == "deadline"
        assert report["lifecycle_state"] == "expired"
        assert sum(report[field] for field in
                   ["market_data_reads", "signals", "fills", "positions", "orders", "private_api_calls"]) == 0
        assert not (session_path / "shadow.sqlite3").exists()
    finally:
        service.close(timeout=10)


@pytest.mark.parametrize("raw", [b"{", b"[]", b"\xff", b"x" * (sp.MAX_BYTES + 1),
                                  b'{"strategy_id":"a","strategy_id":"b","version":"1"}',
                                  b'{"strategy_id":"a","version":"1","x":NaN}'],
                         ids=["broken", "array", "invalid-utf8", "oversized", "duplicate-key", "nan"])
def test_malformed_or_oversized_upload_is_rejected_without_execution(harness, raw):
    service, runtimes = harness
    response = service.upload(raw)
    assert isinstance(response, TelegramResponse)
    assert packages(service) == []
    assert sessions(service) == []
    assert runtimes.started == []


@pytest.mark.parametrize("field", ["code", "adapter", "strategy_id"])
def test_malicious_json_never_executes(harness, tmp_path, field):
    service, runtimes = harness
    marker = tmp_path / "executed"
    payload = json.loads(raw_package())
    payload[field] = f"__import__('pathlib').Path({str(marker)!r}).touch()"
    assert isinstance(service.upload(json.dumps(payload)), TelegramResponse)
    command(service, "approve")
    command(service, "run")
    assert not marker.exists()
    assert not any(row["status"] == "approved" for row in packages(service))
    assert sessions(service) == []
    assert runtimes.started == []


def handler_fixture():
    service = Mock(spec=["upload", "command"])
    service.upload.return_value = TelegramResponse("uploaded")
    service.command.return_value = TelegramResponse("strategy response")
    control = Mock()
    control.main_keyboard.return_value = {"inline_keyboard": []}
    config = TelegramConfig(token="fixture", allowed_user_id="123", allowed_chat_id="456")
    return TelegramHandlers(config, control=control, strategies=service), service, control


STRATEGY_COMMANDS = ["/dashboard", "/strategies"] + [
    f"/strategy_{action} alpha 1" for action in
    ["approve", "reject", "run", "status", "dashboard", "stop", "report"]
]


@pytest.mark.parametrize("text", STRATEGY_COMMANDS)
@pytest.mark.parametrize("user,chat", [(999, 456), (123, 999), (None, 456), (123, None)])
def test_strategy_commands_require_both_authorized_user_and_chat(text, user, chat):
    handlers, service, _ = handler_fixture()
    response = handlers.handle_message(text, user, chat)
    assert "unauthorized" in response.text.lower()
    service.command.assert_not_called()


@pytest.mark.parametrize("text", STRATEGY_COMMANDS)
def test_authorized_strategy_commands_dispatch_to_service(text):
    handlers, service, _ = handler_fixture()
    assert handlers.handle_message(text, 123, 456) == service.command.return_value
    service.command.assert_called_once_with(text)


@pytest.mark.parametrize("user,chat", [(999, 456), (123, 999), (None, 456), (123, None)])
def test_unauthorized_document_does_not_reach_service(user, chat):
    handlers, service, _ = handler_fixture()
    assert "unauthorized" in handlers.handle_document(b"{}", user, chat).text.lower()
    service.upload.assert_not_called()


@pytest.mark.parametrize("user,chat", [(999, 456), (123, 999), (None, 456), (123, None), (123, 456)])
def test_bot_checks_authorization_before_downloading_document(monkeypatch, user, chat):
    handlers, service, _ = handler_fixture()
    bot = TelegramBot("fixture", handlers)
    document = {"file_id": "file-1", "file_name": "package.json", "file_size": 2}
    updates = [{"update_id": 1, "message": {
        "from": {"id": user}, "chat": {"id": chat},
        "document": document}}]
    download = Mock(return_value=b"{}")
    delivery = Mock()
    monkeypatch.setattr(bot, "_get_updates", lambda offset: updates)
    monkeypatch.setattr(bot, "_download_package", download)
    monkeypatch.setattr(bot, "_deliver_response", delivery)
    bot.run(once=True)
    if (user, chat) == (123, 456):
        download.assert_called_once_with(document)
        service.upload.assert_called_once_with(b"{}")
    else:
        download.assert_not_called()
        service.upload.assert_not_called()
    assert delivery.call_count == 1


@pytest.mark.parametrize("name", ["status", "settings", "safety", "help", "source",
                                  "open_trades", "closed_trades", "gates"])
def test_existing_read_only_commands_still_use_control_panel(name):
    handlers, service, control = handler_fixture()
    getattr(control, name).return_value = f"legacy {name}"
    assert handlers.handle_message(f"/{name}", 123, 456).text.startswith(f"legacy {name}")
    getattr(control, name).assert_called_once_with()
    service.command.assert_not_called()
    service.upload.assert_not_called()


class DownloadResponse:
    status_code = 200

    def __init__(self, chunks=(), path="documents/package.json"):
        self.chunks = chunks
        self.path = path
        self.closed = False

    def raise_for_status(self):
        pass

    def json(self):
        return {"ok": True, "result": {"file_path": self.path}}

    def iter_content(self, chunk_size):
        yield from self.chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


def test_download_uses_official_getfile_and_bounded_stream(monkeypatch):
    bot = TelegramBot("fixture", Mock())
    stream = DownloadResponse([b"{", b"}"])
    get = Mock(side_effect=[DownloadResponse(), stream])
    monkeypatch.setattr("src.telegram_bot.requests.get", get)
    assert bot._download_package({"file_id": "f1", "file_name": "p.json", "file_size": 2}) == b"{}"
    first, second = get.call_args_list
    assert first.args == ("https://api.telegram.org/botfixture/getFile",)
    assert first.kwargs["params"] == {"file_id": "f1"}
    assert second.args == ("https://api.telegram.org/file/botfixture/documents/package.json",)
    assert second.kwargs["stream"] is True
    assert first.kwargs["allow_redirects"] is second.kwargs["allow_redirects"] is False
    assert stream.closed


@pytest.mark.parametrize("size", [0, -1, sp.MAX_BYTES + 1, None, True])
def test_invalid_advertised_size_is_rejected_before_getfile(monkeypatch, size):
    get = Mock(side_effect=AssertionError("Download must not start"))
    monkeypatch.setattr("src.telegram_bot.requests.get", get)
    with pytest.raises(ValueError):
        TelegramBot("fixture", Mock())._download_package(
            {"file_id": "f1", "file_name": "p.json", "file_size": size})
    get.assert_not_called()


def test_actual_download_bytes_are_capped_even_when_size_is_underreported(monkeypatch):
    stream = DownloadResponse([b"x" * sp.MAX_BYTES, b"x"])
    get = Mock(side_effect=[DownloadResponse(), stream])
    monkeypatch.setattr("src.telegram_bot.requests.get", get)
    with pytest.raises(ValueError):
        TelegramBot("fixture", Mock())._download_package(
            {"file_id": "f1", "file_name": "p.json", "file_size": 2})
    assert stream.closed


@pytest.mark.parametrize("path", ["https://evil.invalid/p.json", "../secret", "/etc/passwd",
                                  "documents/../secret", "documents//p.json"])
def test_getfile_cannot_redirect_download_to_untrusted_path(monkeypatch, path):
    get = Mock(return_value=DownloadResponse(path=path))
    monkeypatch.setattr("src.telegram_bot.requests.get", get)
    with pytest.raises(ValueError):
        TelegramBot("fixture", Mock())._download_package(
            {"file_id": "f1", "file_name": "p.json", "file_size": 2})
    assert get.call_count == 1


def test_list_pagination_does_not_hide_or_repeat_packages(harness):
    service, runtimes = harness
    for sid in ["one", "two", "three", "four", "five", "six"]:
        service.upload(raw_package(sid))
    ordered = sorted(row["package"]["strategy_id"] for row in packages(service))
    first = service.command("/strategies").text
    second = service.command("/strategies 2").text
    assert all(f"{sid}/1:" in first for sid in ordered[:5])
    assert f"{ordered[5]}/1:" not in first
    assert f"{ordered[5]}/1:" in second
    assert all(f"{sid}/1:" not in second for sid in ordered[:5])
    assert runtimes.started == []


def test_sandbox_dashboard_counts_versions_without_combining_them(harness):
    service, runtimes = harness
    ready(service, "alpha", "1")
    ready(service, "alpha", "2")
    service.upload(raw_package("rejected", "1"))
    command(service, "reject", "rejected", "1")
    command(service, "run", "alpha", "1")
    eventually(lambda: state(service, "alpha") == "running")
    response = service.command("/dashboard")
    assert "running=1" in response.text
    assert "rejected=1" in response.text
    assert "idle=1" in response.text
    assert "versions isolated" in response.text
    assert "not combined" in response.text
    runtimes.release("alpha")


def test_strategy_dashboard_uses_durable_journal_accounting(tmp_path):
    session = tmp_path / "session"
    ledger = session / "shadow.sqlite3"
    metadata = {"initial_balance": "1000"}
    journal = ShadowJournal(ledger, metadata)
    try:
        def seed(state):
            state["signals"] = {key: {"signal_id": key} for key in ("open", "win", "loss")}
            state["market"] = {"BTCUSDT": {"quote": {"bidPrice": "110", "askPrice": "111"}}}
            state["health"] = {"BTCUSDT": {"ready": False, "reason": "stream_gap"}}
            state["positions"] = {"open": {
                "signal_id": "open", "symbol": "BTCUSDT", "side": "LONG", "quantity": "1",
                "entry_price": "101", "entry_quote": {"askPrice": "100"}, "entry_fee": "0.1",
                "funding": "0.02", "gap_exposure": True,
            }}
            state["closed"] = {
                "win": {"signal_id": "win", "symbol": "BTCUSDT", "side": "LONG", "quantity": "1",
                        "entry_price": "101", "entry_quote": {"askPrice": "100"}, "entry_fee": "0.1",
                        "exit_price": "104", "exit_quote": {"bidPrice": "105"}, "exit_fee": "0.1",
                        "funding": "0.2", "net_pnl": "4", "exit_ms": 1},
                "loss": {"signal_id": "loss", "symbol": "BTCUSDT", "side": "LONG", "quantity": "1",
                         "entry_price": "100", "entry_quote": {"askPrice": "100"}, "entry_fee": "0.1",
                         "exit_price": "98", "exit_quote": {"bidPrice": "98"}, "exit_fee": "0.1",
                         "funding": "0", "net_pnl": "-2", "exit_ms": 2},
            }
        journal.transact("seed", "fixture", {}, seed)
    finally:
        journal.close()
    package = json.loads(raw_package())
    row = {"state": "running", "updated_at": datetime.now(timezone.utc).isoformat(), "report": None}
    result = journal_metrics(session, row, package)
    assert result["result_scope"] == "live_shadow"
    assert result["historical_results"] == "not_attached"
    assert result["monthly_return_projection"] is None
    assert result["trades"] == 3 and result["open_positions"] == 1 and result["closed_trades"] == 2
    assert result["win_rate_pct"] == "50"
    assert result["realized_pnl_usdt"] == "2"
    assert result["unrealized_pnl_usdt"] == "8.92"
    assert result["net_pnl_usdt"] == "10.92"
    assert result["period_return_pct"] == "1.092"
    assert result["expectancy_usdt"] == "1"
    assert result["profit_factor"] == "2"
    assert result["max_drawdown_usdt"] == "2"
    assert result["fees_usdt"] == "0.5"
    assert result["slippage_usdt"] == "3"
    assert result["funding_usdt"] == "0.22"
    assert result["data_gaps"] == {
        "available": True,
        "unavailable_symbols": {"BTCUSDT": "stream_gap"},
        "gap_exposed_positions": 1,
    }
    # The product card must display this same durable accounting snapshot.
    from types import SimpleNamespace
    row.update(strategy_id="alpha", version="1", session_id="session", worker_alive=True)
    ui = StrategyService.__new__(StrategyService)
    life = SimpleNamespace(root=tmp_path, status=lambda: [row])
    # Match the lifecycle's fixed sessions path without touching a real runtime.
    (tmp_path / "sessions").mkdir()
    session.rename(tmp_path / "sessions/session")
    card = ui._ui_card({"package": package, "status": "approved"}, life, details=True)
    for expected in ("Сделки: 3", "Открыто: 1", "Закрыто: 2", "Win Rate: 50%", "1.092%",
                     "10.92 USDT", "8.92 USDT", "PF: 2", "0.5 USDT", "3 USDT", "0.22 USDT",
                     "BTCUSDT: stream_gap", "Месячного прогноза нет"):
        assert expected in card.text


def test_diagnostic_dashboard_does_not_invent_financial_metrics(tmp_path):
    session = tmp_path / "diagnostic"
    session.mkdir()
    (session / "runtime_status.json").write_text(json.dumps({
        "started_at": datetime.now(timezone.utc).isoformat(),
        "fills": 0,
        "positions": 0,
    }))
    package = json.loads(raw_synthetic_package())
    result = journal_metrics(session, {"state": "running", "report": None}, package)
    assert result["metrics_source"] == "runtime_status"
    assert result["trades"] == result["open_positions"] == result["closed_trades"] == 0
    for field in ["win_rate_pct", "realized_pnl_usdt", "unrealized_pnl_usdt",
                  "net_pnl_usdt", "period_return_pct", "expectancy_usdt",
                  "profit_factor", "max_drawdown_usdt"]:
        assert result[field] is None


def test_dashboard_text_exposes_gap_reasons_and_metric_scopes():
    data = {
        "strategy_id": "alpha", "version": "1", "status": "running",
        "result_scope": "live_shadow", "runtime_seconds": 5,
        "deadline": "2026-10-02T00:00:00+00:00", "trades": 1,
        "open_positions": 0, "closed_trades": 1, "win_rate_pct": "100",
        "realized_pnl_usdt": "1", "unrealized_pnl_usdt": "0",
        "net_pnl_usdt": "1", "period_return_pct": "0.1",
        "expectancy_usdt": "1", "profit_factor": None,
        "profit_factor_reason": "no realized losses", "max_drawdown_usdt": "0",
        "fees_usdt": "0.1", "slippage_usdt": "0.1", "funding_usdt": "0",
        "data_gaps": {"available": True, "unavailable_symbols": {"ETHUSDT": "stream_gap"},
                      "gap_exposed_positions": 1},
    }
    text = StrategyService._dashboard_text("approved", data)
    assert "PF=infinity (no realized losses)" in text
    assert "max DD (closed realized)=0 USDT" in text
    assert "ETHUSDT:stream_gap" in text
    assert "Historical: not attached; never combined" in text
    assert "Monthly projection: not calculated" in text


def test_report_not_ready_then_completed_and_tampered_file_blocked(harness, monkeypatch):
    service, runtimes = harness
    ready(service)
    assert command(service, "report").documents == ()
    command(service, "run")
    eventually(lambda: len(runtimes.started) == 1)
    assert command(service, "report").documents == ()
    runtimes.release("alpha")
    eventually(lambda: bool(command(service, "report").documents))
    response = command(service, "report")
    report_path = Path(response.documents[0])
    assert report_path == runtimes.paths[0] / "REPORT.json"
    assert json.loads(report_path.read_text())["lifecycle_state"] == "completed"
    original_read = Path.read_text

    def tampered_read(path, *args, **kwargs):
        # A real file edit races with the scheduler's automatic report repair.
        if path == report_path:
            return "{}"
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tampered_read)
    assert command(service, "report").documents == ()


def test_download_failure_does_not_prevent_next_update(monkeypatch):
    handlers, service, control = handler_fixture()
    control.status.return_value = "legacy status"
    bot = TelegramBot("fixture", handlers)
    messages = [
        {"document": {"file_id": "broken"}},
        {"text": "/status"},
    ]
    updates = [{"update_id": index, "message": {
        "from": {"id": 123}, "chat": {"id": 456}, **message}}
        for index, message in enumerate(messages)]
    delivered = []
    monkeypatch.setattr(bot, "_get_updates", lambda offset: updates)
    monkeypatch.setattr(bot, "_download_package", Mock(side_effect=ValueError("invalid")))
    monkeypatch.setattr(bot, "_deliver_response", lambda chat, response: delivered.append(response))
    bot.run(once=True)
    assert len(delivered) == 2
    assert delivered[1].text == "legacy status"
    service.upload.assert_not_called()


@pytest.mark.parametrize("ok", [False, True])
def test_document_delivery_requires_telegram_json_confirmation(monkeypatch, tmp_path, ok):
    document = tmp_path / "REPORT.json"
    document.write_text("{}")
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"ok": ok}
    post = Mock(return_value=response)
    monkeypatch.setattr("src.telegram_bot.requests.post", post)
    bot = TelegramBot("fixture", Mock())
    assert bot._send_document(456, str(document)) is ok
    response.raise_for_status.assert_called_once_with()
    response.json.assert_called_once_with()
    assert post.call_args.args == ("https://api.telegram.org/botfixture/sendDocument",)


@pytest.mark.parametrize("with_stop_event", [False, True])
def test_service_initialization_failure_preserves_existing_panel(monkeypatch, tmp_path, with_stop_event):
    from src import telegram_bot

    config = TelegramConfig(token="fixture", allowed_user_id="123", allowed_chat_id="456")
    control = Mock()
    control.status.return_value = "legacy status"
    control.main_keyboard.return_value = {"inline_keyboard": []}
    factory = Mock(side_effect=RuntimeError("Synthetic initialization failure"))
    monkeypatch.setattr(telegram_bot, "load_telegram_config_from_env", lambda: config)
    monkeypatch.setattr(telegram_bot, "TelegramControlPanel", Mock(return_value=control))
    monkeypatch.setattr("src.telegram_strategy_lifecycle.StrategyService", factory)
    calls = []

    event = threading.Event() if with_stop_event else None

    def run(bot, once=False, stop_event=None):
        assert stop_event is event
        calls.append(once)
        assert bot.handlers.strategies is None
        assert bot.handlers.handle_message("/status", 123, 456).text == "legacy status"
        for text in STRATEGY_COMMANDS:
            assert "unavailable" in bot.handlers.handle_message(text, 123, 456).text.lower()
        assert "unavailable" in bot.handlers.handle_document(b"{}", 123, 456).text.lower()

    monkeypatch.setattr(TelegramBot, "run", run)
    options = {"stop_event": event} if with_stop_event else {}
    telegram_bot.run_telegram_bot(once=True, data_root=str(tmp_path), **options)
    assert calls == [True]
    factory.assert_called_once_with(tmp_path / "strategy_lifecycle_v1", **options)


@pytest.mark.parametrize("stop_at", ["before_poll", "during_poll", "after_first_update"])
@pytest.mark.parametrize("kind", ["message", "document", "callback"])
def test_bot_does_not_dispatch_updates_after_stop(monkeypatch, stop_at, kind):
    event = threading.Event()
    handlers = Mock()
    handlers.strategy_authorized.return_value = True
    bot = TelegramBot("fixture", handlers)
    message = {"from": {"id": 123}, "chat": {"id": 456}, "text": "/strategies"}
    if kind == "document":
        message["document"] = {"file_id": "fixture"}
    if kind == "callback":
        payload = {"callback_query": {"id": "fixture", "from": {"id": 123},
                                      "message": message, "data": "status"}}
    else:
        payload = {"message": message}
    updates = [{"update_id": index, **payload} for index in range(2)]

    def poll(offset):
        if stop_at == "during_poll":
            event.set()
        return updates

    get_updates = Mock(side_effect=poll)
    delivery = Mock(side_effect=lambda *args: event.set())
    download = Mock(return_value=b"{}")
    answer = Mock()
    monkeypatch.setattr(bot, "_get_updates", get_updates)
    monkeypatch.setattr(bot, "_deliver_response", delivery)
    monkeypatch.setattr(bot, "_download_package", download)
    monkeypatch.setattr(bot, "_answer_callback", answer)
    if stop_at == "before_poll":
        event.set()
    bot.run(once=True, stop_event=event)

    count = int(stop_at == "after_first_update")
    assert get_updates.call_count == int(stop_at != "before_poll")
    assert handlers.handle_message.call_count == (count if kind == "message" else 0)
    assert handlers.handle_document.call_count == (count if kind == "document" else 0)
    assert handlers.handle_callback.call_count == (count if kind == "callback" else 0)
    assert delivery.call_count == count
    assert download.call_count == (count if kind == "document" else 0)
    assert answer.call_count == (count if kind == "callback" else 0)


@pytest.mark.parametrize("failure_at", [None, "panel", "poll"])
def test_bot_runner_propagates_stop_and_always_closes_without_timeout(monkeypatch, tmp_path, failure_at):
    from src import telegram_bot

    event = threading.Event()
    service = Mock()
    factory = Mock(return_value=service)
    config = TelegramConfig(token="fixture", allowed_user_id="123", allowed_chat_id="456")
    monkeypatch.setattr(telegram_bot, "load_telegram_config_from_env", lambda: config)
    monkeypatch.setattr("src.telegram_strategy_lifecycle.StrategyService", factory)
    panel = Mock(side_effect=RuntimeError("panel failure")) if failure_at == "panel" else Mock()
    monkeypatch.setattr(telegram_bot, "TelegramControlPanel", panel)
    run = Mock(side_effect=RuntimeError("poll failure")) if failure_at == "poll" else Mock()
    monkeypatch.setattr(TelegramBot, "run", run)
    if failure_at:
        with pytest.raises(RuntimeError, match=f"{failure_at} failure"):
            telegram_bot.run_telegram_bot(data_root=str(tmp_path), stop_event=event)
    else:
        telegram_bot.run_telegram_bot(data_root=str(tmp_path), stop_event=event)
    factory.assert_called_once_with(tmp_path / "strategy_lifecycle_v1", stop_event=event)
    service.close.assert_called_once_with(timeout=None)
    if failure_at != "panel":
        run.assert_called_once_with(once=False, stop_event=event)


def test_external_stop_finalizes_workers_without_explicit_close(tmp_path):
    event = threading.Event()
    runtimes = FakeRuntimes()
    service = StrategyService(tmp_path / "strategies", runtime_factory=runtimes, stop_event=event)
    try:
        assert service.thread.daemon is False
        for sid in ["alpha", "beta", "gamma"]:
            ready(service, sid)
            command(service, "run", sid)
        eventually(lambda: len(runtimes.started) == 2)
        event.set()
        service.thread.join(5)
        assert not service.thread.is_alive()
        assert runtimes.active == 0
        assert all(not thread.is_alive() for thread in runtimes.threads)
        assert ("gamma", "1") not in runtimes.started
        assert {row["strategy_id"]: row["state"] for row in sessions(service)} == {
            "alpha": "paused", "beta": "paused", "gamma": "queued"}
        for path in runtimes.paths:
            assert json.loads((path / "REPORT.json").read_text())["lifecycle_state"] == "paused"
        assert "unavailable" in command(service, "run").text.lower()
    finally:
        event.set()
        service.close(timeout=10)


def test_run_all_returns_only_after_strategy_workers_finalize(monkeypatch, tmp_path):
    from src import run_all as supervisor, telegram_bot
    from src.runtime_status import RuntimeStatusStore

    runtimes = FakeRuntimes()
    services = []
    events = []
    config = TelegramConfig(token="fixture", allowed_user_id="123", allowed_chat_id="456")
    store = RuntimeStatusStore(tmp_path / "runtime/runtime_status.json")

    def factory(root, stop_event=None):
        events.append(stop_event)
        service = StrategyService(root, runtime_factory=runtimes, stop_event=stop_event)
        services.append(service)
        return service

    def poll(bot, once=False, stop_event=None):
        assert stop_event is events[0]
        service = bot.handlers.strategies
        for sid in ["alpha", "beta"]:
            ready(service, sid)
            command(service, "run", sid)
        eventually(lambda: len(runtimes.started) == 2)
        stop_event.set()

    monkeypatch.setattr(supervisor, "install_shutdown_handlers", lambda event, store: events.append(event))
    monkeypatch.setattr(telegram_bot, "load_telegram_config_from_env", lambda: config)
    monkeypatch.setattr(telegram_bot, "TelegramControlPanel", Mock())
    monkeypatch.setattr("src.telegram_strategy_lifecycle.StrategyService", factory)
    monkeypatch.setattr(TelegramBot, "run", poll)
    try:
        result = supervisor.run_all(
            config=supervisor.RunAllConfig(symbols=["BTCUSDT"], timeframe="15m",
                                           candidate_source="production_like_raw", interval_sec=1,
                                           data_root=str(tmp_path)),
            telegram_runner=telegram_bot.run_telegram_bot,
            status_store=store,
            supervisor_runtime_sec=10,
        )
        assert result == 0
        assert len(events) == 2 and events[0] is events[1]
        assert len(services) == 1
        assert len(runtimes.started) == 2
        assert not services[0].thread.is_alive()
        assert runtimes.active == 0
        assert all(not thread.is_alive() for thread in runtimes.threads)
        assert all(row["state"] == "paused" for row in sessions(services[0]))
        for path in runtimes.paths:
            assert json.loads((path / "REPORT.json").read_text())["lifecycle_state"] == "paused"
        assert store.read()["service_state"] == "stopped"
        assert not store.read().get("errors")
    finally:
        for event in events:
            event.set()
        for service in services:
            service.close(timeout=10)


def ui_button(response, label):
    return next(b['callback_data'] for line in response.reply_markup['inline_keyboard']
                for b in line if b['text'] == label)


def test_product_ui_menu_upload_confirmations_and_report(harness):
    from src.telegram_bot import CloudPackageHandlers
    service, runtimes = harness
    config = TelegramConfig(token='fixture', allowed_user_id='1', allowed_chat_id='2')
    handler = CloudPackageHandlers(config, strategies=service)
    menu = handler.handle_message('/start', 1, 2)
    labels = [b['text'] for line in menu.reply_markup['inline_keyboard'] for b in line]
    assert labels == ['Dashboard', 'Добавить стратегию', 'Активные', 'Все стратегии', 'Отчёты', 'Состояние системы']
    assert '/strategy_' not in menu.text
    assert '.json' in handler.handle_callback(ui_button(menu, 'Добавить стратегию'), 1, 2).text
    card = handler.handle_document(raw_package(), 1, 2)
    assert 'не запущена' in card.text and not runtimes.started
    ask = handler.handle_callback(ui_button(card, 'Одобрить'), 1, 2)
    assert packages(service)[0]['status'] == 'validated'
    assert 'Нет доступа' in handler.handle_callback(ui_button(ask, 'Подтвердить: одобрить'), 99, 2).text
    card = handler.handle_callback(ui_button(ask, 'Подтвердить: одобрить'), 1, 2)
    assert packages(service)[0]['status'] == 'approved' and not runtimes.started
    assert 'устарело' in handler.handle_callback(ui_button(ask, 'Подтвердить: одобрить'), 1, 2).text
    ask = handler.handle_callback(ui_button(card, 'Запустить'), 1, 2)
    assert not runtimes.started
    handler.handle_callback(ui_button(ask, 'Отмена'), 1, 2)
    assert 'устарело' in handler.handle_callback(ui_button(ask, 'Подтвердить: запустить'), 1, 2).text
    ask = handler.handle_callback(ui_button(card, 'Запустить'), 1, 2)
    handler.handle_callback(ui_button(ask, 'Подтвердить: запустить'), 1, 2)
    eventually(lambda: len(runtimes.started) == 1)
    listing = handler.handle_callback('ui:active:1', 1, 2)
    card = handler.handle_callback(ui_button(listing, 'alpha/1'), 1, 2)
    assert 'Остановить' in str(card.reply_markup)
    ask = handler.handle_callback(ui_button(card, 'Остановить'), 1, 2)
    assert state(service, 'alpha') == 'running'
    handler.handle_callback(ui_button(ask, 'Подтвердить: остановить'), 1, 2)
    eventually(lambda: state(service, 'alpha') == 'stopped')
    report = handler.handle_callback(ui_button(card, 'Отчёт'), 1, 2)
    assert len(report.documents) == 1 and Path(report.documents[0]).is_file()
    assert 'alpha/1' in str(handler.handle_callback('ui:reports:1', 1, 2).reply_markup)
    assert 'Пока пусто' in handler.handle_callback('ui:active:1', 1, 2).text
    assert len(runtimes.started) == 1


def test_product_ui_reject_expiry_actor_and_changed_state(harness):
    service, runtimes = harness
    card = service.ui('ui:upload', 1, 2, raw_package())
    ask = service.ui(ui_button(card, 'Отклонить'), 1, 2)
    confirm = ui_button(ask, 'Подтвердить: отклонить')
    assert 'устарело' in service.ui(confirm, 2, 2).text
    assert 'устарело' in service.ui(confirm, 1, 3).text
    service.ui(confirm, 1, 2)
    assert packages(service)[0]['status'] == 'rejected' and not runtimes.started
    card = service.ui('ui:upload', 1, 2, raw_package('beta'))
    ask = service.ui(ui_button(card, 'Одобрить'), 1, 2)
    confirm = ui_button(ask, 'Подтвердить: одобрить')
    token = confirm.split(':')[-1]
    pending = service.ui_confirmations[token]
    service.ui_confirmations[token] = (0,) + pending[1:]
    assert 'устарело' in service.ui(confirm, 1, 2).text
    ask = service.ui(ui_button(card, 'Одобрить'), 1, 2)
    command(service, 'reject', 'beta')
    assert 'Состояние изменилось' in service.ui(ui_button(ask, 'Подтвердить: одобрить'), 1, 2).text
    assert not runtimes.started


def test_product_ui_pagination_versions_and_restart_token(harness):
    service, runtimes = harness
    for n in range(7):
        service.ui('ui:upload', 1, 2, raw_package('alpha', str(n)))
    page = service.ui('ui:all:1', 1, 2)
    assert '7' in page.text
    card = service.ui(ui_button(page, 'alpha/0'), 1, 2)
    ask = service.ui(ui_button(card, 'Одобрить'), 1, 2)
    service.ui_confirmations.clear()  # Confirmations are process-local, never persisted.
    assert 'устарело' in service.ui(ui_button(ask, 'Подтвердить: одобрить'), 1, 2).text
    page2 = service.ui(ui_button(page, 'Далее →'), 1, 2)
    assert 'alpha/5' in str(page2.reply_markup) and 'alpha/0' not in str(page2.reply_markup)
    for response in (page, page2, card, ask):
        assert len(response.text) < 3900
        assert all(len(b['callback_data'].encode()) <= 64 for line in response.reply_markup['inline_keyboard'] for b in line)
    assert all(p['status'] == 'validated' for p in packages(service))
    assert not runtimes.started
