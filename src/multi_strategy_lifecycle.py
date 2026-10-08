"""Local, single-owner supervisor for isolated approved shadow packages."""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .strategy_packages import PackageError, PackageStore, canonical, sha, validate_package


TERMINAL = {"stopped", "completed", "failed", "expired"}


def utcnow():
    return datetime.now(timezone.utc)


def deadline(package):
    return datetime.fromisoformat(package["deadline"].replace("Z", "+00:00"))


def runtime_hash():
    digest = hashlib.sha256()
    for name in ("multi_strategy_lifecycle.py", "package_shadow_runtime.py"):
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


def write_json(path, value):
    """Materialized views only; the SQLite transaction is the source of truth."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        stream.write(canonical(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Lifecycle:
    """Call tick/serve explicitly. Construction never launches research.

    Workers are threads in this owner process, each with its own engine, public
    client and SQLite journal. A supervisor crash therefore cannot leave orphan
    child workers. A filesystem lock prevents a second owner of the same root.
    """
    def __init__(self, root, package_store_path, max_concurrent_strategies=2,
                 runtime_factory=None, clock=None, stopped_startup=False):
        from .cloud_release import schema_preflight, schema_check
        tables = {"settings": "id value", "sessions": "seq session_id strategy_id version snapshot digest runtime_hash state requested created_at updated_at report"}
        if type(max_concurrent_strategies) is not int or max_concurrent_strategies < 1:
            raise ValueError("positive integer concurrency required")
        self.root = Path(root).resolve()
        schema_preflight(self.root / "lifecycle.sqlite3", tables)
        self.package_store_path = Path(package_store_path).resolve()
        if not self.package_store_path.is_file():
            raise PackageError("existing package store required")
        if self.root.exists() and any(self.root.iterdir()) and not (self.root / "lifecycle.sqlite3").is_file():
            raise ValueError("use a new dedicated lifecycle root")
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / "owner.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.path = self.root / "lifecycle.sqlite3"
            self.limit = max_concurrent_strategies
            self.clock = clock or utcnow
            if runtime_factory is None:
                from .package_shadow_runtime import PackageShadowRuntime
                runtime_factory = PackageShadowRuntime
            self.factory = runtime_factory
            self.workers = {}
            self.blockers = {}
            self.pause = threading.Event()
            self.closed = False
            self.stopped_startup = stopped_startup
            self.admitted = set()
            self.mutex = threading.RLock()
            with self._db() as db:
                fresh = schema_check(db, tables)
                db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT)")
                settings = canonical(dict(package_store=str(self.package_store_path), max_concurrent_strategies=self.limit))
                db.execute("INSERT OR IGNORE INTO settings VALUES (1,?)", (settings,))
                if db.execute("SELECT value FROM settings WHERE id=1").fetchone()[0] != settings:
                    raise ValueError("persisted configuration mismatch")
                db.execute("CREATE TABLE IF NOT EXISTS sessions (seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT UNIQUE, strategy_id TEXT, version TEXT, snapshot TEXT, digest TEXT, runtime_hash TEXT, state TEXT, requested TEXT, created_at TEXT, updated_at TEXT, report TEXT, UNIQUE(strategy_id,version))")
                db.execute("CREATE TRIGGER IF NOT EXISTS immutable_session BEFORE UPDATE ON sessions WHEN NEW.session_id IS NOT OLD.session_id OR NEW.strategy_id IS NOT OLD.strategy_id OR NEW.version IS NOT OLD.version OR NEW.snapshot IS NOT OLD.snapshot OR NEW.digest IS NOT OLD.digest OR NEW.runtime_hash IS NOT OLD.runtime_hash BEGIN SELECT RAISE(ABORT,'immutable session snapshot'); END")
                if fresh:
                    db.execute("PRAGMA user_version=1")
            (self.root / "sessions").mkdir(exist_ok=True)
        except BaseException:
            self.lock.close()
            raise

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        # Connection context managers do not close connections themselves.
        class Connection:
            def __enter__(inner):
                return db
            def __exit__(inner, kind, value, tb):
                try:
                    db.rollback() if kind else db.commit()
                finally:
                    db.close()
        return Connection()

    def status(self):
        with self._db() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM sessions ORDER BY seq")]
        for row in rows:
            worker = self.workers.get(row["session_id"])
            row["worker_alive"] = bool(worker and worker.is_alive())
            row["recovery_pending"] = row["state"] in {"running", "paused"} and not row["worker_alive"]
            row["startup_held"] = self.stopped_startup and row["session_id"] not in self.admitted and row["state"] not in TERMINAL
            if row["session_id"] in self.blockers:
                row["persistence_blocker"] = self.blockers[row["session_id"]]
        return rows

    def _row(self, session_id):
        with self._db() as db:
            row = db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise ValueError("unknown session")
        return dict(row)

    def _approved(self, strategy_id, version):
        store = PackageStore(self.package_store_path)
        try:
            row = store.get(strategy_id, version)
        finally:
            store.close()
        if row["status"] != "approved":
            raise PackageError("only approved packages may run")
        return row

    def _verified(self, row):
        accepted = self._approved(row["strategy_id"], row["version"])
        if sha(row["snapshot"]) != row["digest"] or accepted["package_sha256"] != row["digest"]:
            raise PackageError("session/package snapshot integrity mismatch")
        if row["runtime_hash"] != runtime_hash():
            raise PackageError("lifecycle runtime code changed; recovery blocked")
        return validate_package(row["snapshot"], self.clock())

    def enqueue(self, strategy_id, version):
        with self.mutex:
            if self.closed or self.pause.is_set():
                raise RuntimeError("supervisor closing")
            accepted = self._approved(strategy_id, version)
            package = validate_package(canonical(accepted["snapshot"]), self.clock())
            with self._db() as db:
                old = db.execute("SELECT session_id FROM sessions WHERE strategy_id=? AND version=?", (strategy_id, version)).fetchone()
                if old:
                    if self.stopped_startup:
                        self._verified(self._row(old[0]))
                        self.admitted.add(old[0])
                    return old[0]
                session_id = "package-" + uuid.uuid4().hex
                now = self.clock().isoformat()
                db.execute("INSERT INTO sessions(session_id,strategy_id,version,snapshot,digest,runtime_hash,state,requested,created_at,updated_at) VALUES (?,?,?,?,?,?,'queued','run',?,?)",
                           (session_id, strategy_id, version, canonical(package), accepted["package_sha256"], runtime_hash(), now, now))
            self.admitted.add(session_id)
            return session_id

    def stop(self, session_id):
        with self.mutex:
            if self.closed:
                raise RuntimeError("supervisor closed")
            row = self._row(session_id)
            if row["state"] in TERMINAL:
                return
            with self._db() as db:
                db.execute("UPDATE sessions SET requested='stop',updated_at=? WHERE session_id=?", (self.clock().isoformat(), session_id))

    def _finish(self, session_id, state, report):
        from .package_shadow_runtime import saved_state_report
        path = self.root / "sessions" / session_id
        try:
            preserved = saved_state_report(path)
        except Exception as exc:
            preserved = {"report_complete": False, "ledger_read_error": type(exc).__name__}
        report = dict(report, preserved_ledger=preserved)
        report = dict(report, session_id=session_id, lifecycle_state=state,
                      finished_at=self.clock().isoformat())
        with self._db() as db:
            db.execute("UPDATE sessions SET state=?,report=?,updated_at=? WHERE session_id=?", (state, canonical(report), self.clock().isoformat(), session_id))
        path.mkdir(exist_ok=True)
        write_json(path / "REPORT.json", report)

    def _worker(self, session_id):
        try:
            row = self._row(session_id)
            package = self._verified(row)
            path = self.root / "sessions" / session_id
            path.mkdir(exist_ok=True)
            snapshot = dict(package=package, package_sha256=row["digest"], runtime_hash=row["runtime_hash"])
            target = path / "accepted_package.json"
            if target.exists():
                if json.loads(target.read_text()) != snapshot:
                    raise PackageError("on-disk snapshot tampered")
            else:
                write_json(target, snapshot)

            def should_stop():
                return (self.pause.is_set() or self.clock() >= deadline(package)
                        or self._row(session_id)["requested"] == "stop")

            if should_stop():
                report = {"not_started": True}
            else:
                report = self.factory(package, path, should_stop).run()
            row = self._row(session_id)
            state = ("expired" if self.clock() >= deadline(package) else
                     "stopped" if row["requested"] == "stop" else
                     "paused" if self.pause.is_set() else "completed")
            self._finish(session_id, state, report)
        except BaseException as exc:
            # No forced liquidation, retries or deletion of journal/positions.
            try:
                self._finish(session_id, "failed", {"error_type": type(exc).__name__, "error": str(exc),
                             "journal_preserved": True, "report_complete": False})
            except BaseException as persistence_error:
                self.blockers[session_id] = type(persistence_error).__name__

    def tick(self):
        with self.mutex:
            if self.closed or self.pause.is_set():
                raise RuntimeError("supervisor closing")
            for sid, worker in list(self.workers.items()):
                if not worker.is_alive():
                    worker.join()
                    del self.workers[sid]
            for row in self.status():
                sid = row["session_id"]
                if sid in self.workers or sid in self.blockers:
                    continue
                if row["state"] in TERMINAL:
                    if row["report"] is not None:
                        path = self.root / "sessions" / sid
                        path.mkdir(exist_ok=True)
                        target = path / "REPORT.json"
                        expected = json.loads(row["report"])
                        try:
                            actual = json.loads(target.read_text()) if target.exists() else None
                        except (ValueError, OSError):
                            actual = None
                        if actual != expected:
                            write_json(target, expected)
                    continue
                if row["requested"] == "stop":
                    self._finish(sid, "stopped", {"journal_preserved": True, "not_restarted": True})
                    continue
                try:
                    package = json.loads(row["snapshot"])
                    # Verify integrity even when the deadline has already passed.
                    accepted = self._approved(row["strategy_id"], row["version"])
                    if sha(row["snapshot"]) != row["digest"] or accepted["package_sha256"] != row["digest"] or row["runtime_hash"] != runtime_hash():
                        raise PackageError("recovery integrity mismatch")
                    if self.clock() >= deadline(package):
                        self._finish(sid, "expired", {"journal_preserved": True, "not_restarted": True})
                        continue
                    self._verified(row)
                except Exception as exc:
                    self._finish(sid, "failed", {"error_type": type(exc).__name__, "error": str(exc), "not_restarted": True})
                    continue
                if self.stopped_startup and sid not in self.admitted:
                    continue
                if len(self.workers) >= self.limit:
                    continue
                with self._db() as db:
                    db.execute("UPDATE sessions SET state='running',updated_at=? WHERE session_id=?", (self.clock().isoformat(), sid))
                worker = threading.Thread(target=self._worker, args=(sid,), name=sid, daemon=True)
                self.workers[sid] = worker
                try:
                    worker.start()
                except Exception as exc:
                    del self.workers[sid]
                    self._finish(sid, "failed", {"error_type": type(exc).__name__, "not_started": True})

    def serve(self, interval=0.25):
        if interval <= 0:
            raise ValueError("positive poll interval required")
        while not self.pause.is_set():
            self.tick()
            self.pause.wait(interval)

    def close(self, timeout=10):
        """Cooperative supervisor pause, not a strategy Stop. Never force-kill."""
        with self.mutex:
            if self.closed:
                return
            self.pause.set()
            until = time.monotonic() + timeout
            for worker in self.workers.values():
                worker.join(max(0, until - time.monotonic()))
            if any(worker.is_alive() for worker in self.workers.values()):
                raise TimeoutError("workers still finalizing; owner lock retained")
            self.closed = True
            self.lock.close()
