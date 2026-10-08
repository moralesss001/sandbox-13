import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from src import cloud_release as cloud
from src.live_paper_storage import ShadowJournal
from src.multi_strategy_lifecycle import Lifecycle
from src.strategy_packages import PackageStore, example_package, canonical


def test_manifest_source_only_and_tamper(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    source = tmp_path / "src/example.py"
    source.write_text("pass\n")
    path = tmp_path / "release-manifest.json"
    path.write_text(json.dumps(dict(schema=1, revision="source-test", files={"src/example.py": cloud.digest(source)})))
    monkeypatch.setenv("CRYPTO13_CLOUD_V1", "1")
    monkeypatch.setenv("CRYPTO13_RELEASE_SHA256", cloud.digest(path))
    assert cloud.verify_release(tmp_path)["revision"] == "source-test"
    source.write_text("changed\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        cloud.verify_release(tmp_path)


def test_manifest_pin_required(tmp_path, monkeypatch):
    (tmp_path / "release-manifest.json").write_text('{"schema":1,"revision":"test","files":{}}')
    monkeypatch.setenv("CRYPTO13_CLOUD_V1", "1")
    monkeypatch.delenv("CRYPTO13_RELEASE_SHA256", raising=False)
    with pytest.raises(ValueError, match="externally pinned"):
        cloud.verify_release(tmp_path)


def test_snapshot_without_git(monkeypatch):
    from src.live_shadow import new_snapshot
    monkeypatch.setenv("CRYPTO13_CLOUD_V1", "1")
    monkeypatch.setattr(cloud, "verify_release", lambda *a: {"revision": "source-test"})
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: pytest.fail("Git invoked"))
    assert new_snapshot(["BTCUSDT"])["code_revision"] == "source-test"


@pytest.mark.parametrize("factory", [lambda p: PackageStore(p), lambda p: ShadowJournal(p, {"initial_balance": "1000"})])
@pytest.mark.parametrize("version", [0, 2])
def test_incompatible_database_untouched(tmp_path, monkeypatch, factory, version):
    path = tmp_path / "state.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE unrelated (x)")
    db.execute("PRAGMA user_version=" + str(version))
    db.commit()
    db.close()
    before = path.read_bytes()
    monkeypatch.setenv("CRYPTO13_CLOUD_V1", "1")
    with pytest.raises(ValueError):
        factory(path)
    assert path.read_bytes() == before


def test_new_schema_and_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYPTO13_CLOUD_V1", "1")
    for name, factory in [("packages", PackageStore), ("shadow", lambda p: ShadowJournal(p, {"initial_balance": "1000"}))]:
        path = tmp_path / (name + ".sqlite3")
        obj = factory(path)
        assert obj.db.execute("PRAGMA user_version").fetchone()[0] == 1
        obj.close()
        obj = factory(path)
        obj.close()


def test_single_receiver(tmp_path):
    with cloud.receiver_guard(tmp_path):
        with pytest.raises(BlockingIOError):
            with cloud.receiver_guard(tmp_path):
                pytest.fail("duplicate receiver")
    with cloud.receiver_guard(tmp_path):
        pass


def test_mount_fail_closed(tmp_path):
    with pytest.raises(ValueError):
        cloud.validate_mount(tmp_path)


def test_persistent_mount_requires_exact_writable_mount(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda p: True)
    monkeypatch.setattr(Path, "is_symlink", lambda p: False)
    monkeypatch.setattr(cloud.os, "access", lambda *a: True)
    monkeypatch.setattr(Path, "read_text", lambda p: "1 0 0:1 / / rw - overlay overlay rw\n")
    with pytest.raises(ValueError, match="mount not confirmed"):
        cloud.validate_mount("/app/data")
    monkeypatch.setattr(Path, "read_text", lambda p: "2 1 0:2 / /app/data rw - ext4 /dev/test rw\n")
    assert cloud.validate_mount("/app/data") == Path("/app/data")


def test_run_all_cloud_does_not_construct_old_manager(monkeypatch):
    from src import run_all
    monkeypatch.setenv("CRYPTO13_CLOUD_V1", "1")
    monkeypatch.setattr(cloud, "run_cloud", lambda *a: 0)
    monkeypatch.setattr(run_all, "ResearchSessionManager", lambda *a, **k: pytest.fail("old runtime touched"))
    assert run_all.run_all(dry_run=True) == 0


def test_cloud_restart_holds_queue_until_explicit_request(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYPTO13_CLOUD_V1", "1")
    now = datetime.now(timezone.utc)
    clock = [now]
    store = PackageStore(tmp_path / "packages.sqlite3")
    package = example_package("cloud-fixture", "1", (now + timedelta(hours=1)).isoformat())
    store.upload(canonical(package))
    store.validate("cloud-fixture", "1")
    store.approve("cloud-fixture", "1")
    starts = []

    class Runtime:
        def __init__(self, package, path, stop):
            self.stop = stop

        def run(self):
            starts.append(1)
            return {"synthetic": True}

    first = Lifecycle(tmp_path / "runtime", store.path, runtime_factory=Runtime, clock=lambda: clock[0], stopped_startup=True)
    sid = first.enqueue("cloud-fixture", "1")
    first.close()
    second = Lifecycle(tmp_path / "runtime", store.path, runtime_factory=Runtime, clock=lambda: clock[0], stopped_startup=True)
    second.tick()
    assert not starts
    assert second.status()[0]["startup_held"] is True
    assert second.enqueue("cloud-fixture", "1") == sid
    assert second.enqueue("cloud-fixture", "1") == sid
    second.tick()
    for worker in second.workers.values():
        worker.join(3)
    assert starts == [1]
    second.tick()
    assert starts == [1]
    second.close()
    store.close()


def test_expired_queue_never_starts(tmp_path):
    now = datetime.now(timezone.utc)
    clock = [now]
    store = PackageStore(tmp_path / "p.sqlite3")
    package = example_package("deadline", "1", (now + timedelta(minutes=1)).isoformat())
    store.upload(canonical(package))
    store.validate("deadline", "1")
    store.approve("deadline", "1")
    life = Lifecycle(tmp_path / "runtime", store.path, runtime_factory=lambda *a: pytest.fail("expired worker started"), clock=lambda: clock[0], stopped_startup=True)
    life.enqueue("deadline", "1")
    clock[0] += timedelta(minutes=2)
    life.tick()
    assert life.status()[0]["state"] == "expired"
    life.close()
    store.close()


def test_cloud_telegram_rejects_old_controls():
    from src.telegram_bot import CloudPackageHandlers
    class Config:
        def is_allowed_user(self, value): return value == 1
        def is_allowed_chat(self, value): return value == 2
    class Service:
        def command(self, *a): pytest.fail("unexpected strategy command")
        def ui(self, data, *a):
            from src.telegram_buttons import TelegramResponse
            assert data == "ui:home"
            return TelegramResponse("Главное меню")
    handler = CloudPackageHandlers(Config(), Service())
    assert "Главное меню" in handler.handle_message("/start_live", 1, 2).text
    assert "отключены" in handler.handle_callback("start_confirm", 1, 2).text
    assert "Нет доступа" in handler.handle_message("/strategy_run a 1", 9, 2).text


def test_receiver_not_started_when_service_fails(tmp_path, monkeypatch):
    from src import telegram_bot as bot
    from src import telegram_strategy_lifecycle as service
    monkeypatch.setenv("CRYPTO13_CLOUD_V1", "1")
    monkeypatch.setattr(cloud, "preflight", lambda *a: tmp_path)
    monkeypatch.setattr(bot, "load_telegram_config_from_env", lambda: object())
    def fail(*a, **k):
        raise RuntimeError("synthetic init failure")
    monkeypatch.setattr(service, "StrategyService", fail)
    monkeypatch.setattr(bot.TelegramBot, "run", lambda *a, **k: pytest.fail("poller started"))
    with pytest.raises(RuntimeError, match="synthetic"):
        bot.run_telegram_bot(once=True)
    with cloud.receiver_guard(tmp_path):
        pass


def test_pending_telegram_run_not_replayed(monkeypatch):
    from src.telegram_bot import TelegramBot
    class Handlers:
        def handle_message(self, *a): pytest.fail("old command dispatched")
    bot = TelegramBot("fixture-not-a-token", Handlers())
    bot.cloud_started_at = 100
    monkeypatch.setattr(bot, "_get_updates", lambda offset: [{"update_id": 1, "message": {"date": 99, "text": "/strategy_run x 1"}}])
    bot.run(once=True)


def test_cloud_callbacks_reach_handler_even_from_older_menu(monkeypatch):
    from src.telegram_bot import TelegramBot
    from src.telegram_buttons import TelegramResponse
    calls = []
    class Handlers:
        def handle_callback(self, *args):
            calls.append(args)
            return TelegramResponse("menu")
        def handle_message(self, *args):
            pytest.fail("pre-start command replayed")
    bot = TelegramBot("fixture-not-a-token", Handlers())
    bot.cloud_started_at = 100
    monkeypatch.setattr(bot, "_get_updates", lambda offset: [
        {"update_id": 1, "message": {"date": 99, "text": "/strategy_run x 1"}},
        {"update_id": 2, "callback_query": {"id": "cb", "data": "ui:home", "from": {"id": 1},
                                           "message": {"date": 99, "chat": {"id": 2}}}},
    ])
    answers, delivered = [], []
    monkeypatch.setattr(bot, "_answer_callback", answers.append)
    monkeypatch.setattr(bot, "_deliver_response", lambda *args: delivered.append(args))
    bot.run(once=True)
    assert calls == [("ui:home", 1, 2)]
    assert answers == ["cb"] and len(delivered) == 1


def test_lifecycle_unknown_version_preserved(tmp_path, monkeypatch):
    store = PackageStore(tmp_path / "p.sqlite3")
    life = Lifecycle(tmp_path / "runtime", store.path)
    life.close()
    path = tmp_path / "runtime/lifecycle.sqlite3"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=99")
    db.close()
    before = path.read_bytes()
    monkeypatch.setenv("CRYPTO13_CLOUD_V1", "1")
    with pytest.raises(ValueError):
        Lifecycle(tmp_path / "runtime", store.path)
    assert path.read_bytes() == before
    store.close()
