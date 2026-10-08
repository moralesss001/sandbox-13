"""Source-only release checks; no strategies or exchange execution."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parent.parent
NAMESPACE = "cloud_packages_v1"


def enabled():
    return os.environ.get("CRYPTO13_CLOUD_V1") == "1"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_release(root=ROOT):
    root = Path(root).resolve()
    path = root / "release-manifest.json"
    manifest = json.loads(path.read_text())
    if manifest.get("schema") != 1 or not manifest.get("revision"):
        raise ValueError("invalid release manifest")
    expected = os.environ.get("CRYPTO13_RELEASE_SHA256")
    if enabled() and (not expected or digest(path) != expected):
        raise ValueError("externally pinned release manifest SHA256 required")
    files = manifest["files"]
    for name, sha in files.items():
        target = root / name
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise ValueError("unsafe release path")
        if digest(target) != sha:
            raise ValueError("release source hash mismatch: " + name)
    actual = {str(p.relative_to(root)) for p in (root / "src").rglob("*.py")}
    if actual != {p for p in files if p.startswith("src/") and p.endswith(".py")}:
        raise ValueError("unlisted runtime source")
    return manifest


def schema_check(db, tables):
    """Reject unsupported schemas before DDL/journal mode changes. No migration."""
    version = db.execute("PRAGMA user_version").fetchone()[0]
    existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if version not in {0, 1} or (version == 0 and existing and enabled()):
        raise ValueError("incompatible SQLite schema; explicit new namespace required")
    if version == 1:
        if not set(tables).issubset(existing) or (enabled() and existing != set(tables)):
            raise ValueError("SQLite table schema mismatch")
        for table, columns in tables.items():
            actual = tuple(r[1] for r in db.execute('PRAGMA table_info("' + table + '")'))
            if actual != tuple(columns.split()):
                raise ValueError("SQLite column schema mismatch")
    return not existing


def schema_preflight(path, tables):
    path = Path(path)
    if path.exists():
        if path.is_symlink():
            raise ValueError("symlink database rejected")
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            schema_check(db, tables)
        finally:
            db.close()


@contextmanager
def receiver_guard(root):
    """Single host/volume only. Railway is the sole owner after cutover."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "telegram-receiver.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def validate_mount(data_root):
    root = Path(data_root)
    if str(root) != "/app/data" or root.is_symlink() or not root.is_dir():
        raise ValueError("persistent /app/data required")
    # Container root is not evidence of a mounted persistent data volume.
    records = Path("/proc/self/mountinfo").read_text().splitlines()
    if not any(len(line.split()) > 5 and line.split()[4] == "/app/data" and
               "rw" in line.split()[5].split(",") for line in records):
        raise ValueError("writable /app/data mount not confirmed")
    if not os.access(root, os.W_OK | os.X_OK):
        raise ValueError("data mount not writable")
    return root


def preflight(data_root):
    if os.environ.get("API_MODE", "paper") != "paper":
        raise ValueError("cloud requires paper mode")
    for name in ("ALLOW_REAL_ORDERS", "ALLOW_TESTNET_ORDERS", "PRODUCTION_TRADING_ENABLED"):
        if os.environ.get(name, "false").lower() not in {"0", "false", "off", "no", ""}:
            raise ValueError("orders forbidden")
    verify_release()
    namespace = validate_mount(data_root) / NAMESPACE
    if namespace.is_symlink():
        raise ValueError("symlink cloud namespace forbidden")
    return namespace


def run_cloud(data_root, dry_run=False, runtime_sec=None):
    import signal
    import threading
    from .telegram_bot import run_telegram_bot
    preflight(data_root)
    if dry_run:
        return 0
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    timer = None
    if runtime_sec is not None:
        timer = threading.Timer(runtime_sec, stop.set)
        timer.start()
    try:
        run_telegram_bot(data_root=data_root, stop_event=stop)
    finally:
        if timer:
            timer.cancel()
    return 0
