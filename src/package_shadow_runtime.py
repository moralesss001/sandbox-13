"""Approved-package wrapper; unchanged legacy signals and model execution."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

from .live_shadow import LegacyShadowEngine, legacy_snapshot
from .multi_strategy_lifecycle import deadline, write_json
from .shadow_execution import StandardShadowExecution, number
from .strategy_packages import SYNTHETIC_ADAPTER, canonical, sha, validate_package


class GuardedJournal:
    """Check admission limits inside the same transaction that creates a fill."""
    def __init__(self, journal, package, should_stop, clock_ms=None):
        self.journal = journal
        self.package = json.loads(canonical(package))
        self.metadata = journal.read()["metadata"]
        self.should_stop = should_stop
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def __getattr__(self, name):
        return getattr(self.journal, name)

    def transact(self, key, kind, payload, mutate):
        def guarded(state):
            if kind == "model_entry":
                p = self.package
                limits = p["safety_limits"]
                if state["metadata"] != self.metadata:
                    raise ValueError("runtime metadata changed")
                for field, key in (("fixed_notional_usdt", "fixed_notional_usdt"),
                                   ("fee_rate", "fee_rate"), ("execution_penalty", "adverse_slippage"),
                                   ("latency_ms", "latency_ms"), ("max_quote_age_ms", "max_quote_age_ms")):
                    if state["metadata"][field] != p["execution_model"][key]:
                        raise ValueError("package execution mismatch: " + field)
                if self.should_stop() or self.clock_ms() >= int(deadline(p).timestamp() * 1000):
                    raise ValueError("package stopped or deadline reached")
                for field, expected in (("paper_only", True), ("private_api", False),
                                        ("real_orders", False), ("testnet_orders", False)):
                    if limits[field] is not expected or state["metadata"]["safety"][field] is not expected:
                        raise ValueError("unsafe package/runtime flags")
                if len(state["positions"]) >= limits["max_open_positions"]:
                    raise ValueError("package max_open_positions reached")
                reserved = sum((number(v["entry_notional"]) for v in state["positions"].values()), number("0"))
                notional = number(p["execution_model"]["fixed_notional_usdt"])
                if number(state["metadata"]["fixed_notional_usdt"]) != notional:
                    raise ValueError("package/runtime notional mismatch")
                if reserved + notional > number(limits["max_total_notional_usdt"]):
                    raise ValueError("package max_total_notional reached")
                signal = state["signals"][payload["signal_id"]]
                if signal["symbol"] not in p["universe"]:
                    raise ValueError("symbol outside package universe")
            mutate(state)
        return self.journal.transact(key, kind, payload, guarded)


class PackageEngine(LegacyShadowEngine):
    def __init__(self, path, metadata, package, should_stop, **kwargs):
        self.package_stop = should_stop
        try:
            super().__init__(path, metadata=metadata, **kwargs)
            self.execution = StandardShadowExecution(GuardedJournal(self.journal, package, should_stop))
        except BaseException:
            if hasattr(self, "closed"):
                self.close()
            raise

    def _should_stop(self):
        if self.package_stop():
            self.stop_requested = True
        return super()._should_stop()

    def publish_status(self):
        self._should_stop()
        payload = super().publish_status()
        write_json(self.root / "runtime_status.json", payload)
        return payload


def saved_state_report(path):
    """Read the ledger without opening an engine or changing unresolved positions."""
    path = Path(path)
    ledger = path / "shadow.sqlite3"
    if not ledger.exists():
        return {"journal_exists": False, "positions": {}, "closed": {}}
    db = sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)
    try:
        state = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
    finally:
        db.close()
    status_path = path / "runtime_status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else None
    return dict(journal_exists=True, signal_count=len(state["signals"]),
                positions=state["positions"], closed=state["closed"],
                balance=state["balance"], health=state["health"], funding=state["funding"],
                last_status=status, unrealized_valuation="last recorded quote, not guaranteed current",
                unresolved_positions_not_liquidated=True, model_fills_only=True)


class SyntheticNoopRuntime:
    """Durable lifecycle diagnostic with no market or execution dependencies."""
    def __init__(self, package, path, should_stop):
        self.package = package
        self.path = Path(path)
        self.should_stop = should_stop

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    def run(self):
        package = validate_package(canonical(self.package))
        if package["adapter"] != SYNTHETIC_ADAPTER:
            raise ValueError("synthetic runtime requires synthetic adapter")
        self.path.mkdir(parents=True, exist_ok=True)
        binding = sha(canonical(package))
        marker_path = self.path / "runtime_initialization.json"
        snapshot_path = self.path / "config_snapshot.json"
        status_path = self.path / "runtime_status.json"
        snapshot = {
            "adapter": SYNTHETIC_ADAPTER,
            "strategy_id": package["strategy_id"],
            "strategy_version": package["version"],
            "package_sha256": binding,
            "deadline": package["deadline"],
            "safety_limits": package["safety_limits"],
            "execution_model": package["execution_model"],
        }
        marker = {"adapter": SYNTHETIC_ADAPTER, "package_sha256": binding,
                  "phase": "initialized"}
        if marker_path.exists() or snapshot_path.exists():
            if not marker_path.is_file() or not snapshot_path.is_file():
                raise ValueError("synthetic recovery snapshot incomplete")
            if json.loads(marker_path.read_text()) != marker:
                raise ValueError("synthetic initialization marker mismatch")
            if json.loads(snapshot_path.read_text()) != snapshot:
                raise ValueError("synthetic package snapshot mismatch")
        else:
            write_json(snapshot_path, snapshot)
            write_json(marker_path, marker)

        started_at = self._now().isoformat()
        if status_path.exists():
            previous = json.loads(status_path.read_text())
            if previous.get("package_sha256") != binding:
                raise ValueError("synthetic runtime status mismatch")
            started_at = previous.get("started_at", started_at)
        status = {
            "adapter": SYNTHETIC_ADAPTER,
            "runtime_state": "running",
            "package_sha256": binding,
            "strategy_id": package["strategy_id"],
            "strategy_version": package["version"],
            "started_at": started_at,
            "resumed_at": self._now().isoformat(),
            "market_data_reads": 0,
            "signals": 0,
            "fills": 0,
            "positions": 0,
            "orders": 0,
            "private_api_calls": 0,
        }
        write_json(status_path, status)
        poll_seconds = package["frozen_parameters"]["poll_interval_ms"] / 1000
        while not self.should_stop() and self._now() < deadline(package):
            time.sleep(poll_seconds)
        exit_reason = "deadline" if self._now() >= deadline(package) else "cooperative_stop"
        finished_at = self._now().isoformat()
        report = dict(status, runtime_state="finished", exit_reason=exit_reason,
                      finished_at=finished_at, resumed_at=status["resumed_at"])
        write_json(status_path, report)
        return report


class PackageShadowRuntime:
    def __init__(self, package, path, should_stop):
        self.package = validate_package(canonical(package))
        self.path = Path(path)
        self.should_stop = should_stop

    def run(self):
        # Recheck immediately before engine initialization, including recovery.
        package = validate_package(canonical(self.package))
        if package["adapter"] == SYNTHETIC_ADAPTER:
            return SyntheticNoopRuntime(package, self.path, self.should_stop).run()
        target = self.path / "config_snapshot.json"
        ledger = self.path / "shadow.sqlite3"
        phase_path = self.path / "runtime_initialization.json"
        binding = sha(canonical(package))
        if phase_path.exists():
            phase = json.loads(phase_path.read_text())
            if phase.get("package_sha256") != binding or phase.get("phase") not in {"initializing", "initialized"}:
                raise ValueError("invalid runtime initialization marker")
        else:
            if target.exists() or ledger.exists():
                raise ValueError("runtime initialization marker missing")
            phase = dict(package_sha256=binding, phase="initializing")
            write_json(phase_path, phase)
        initialized = phase["phase"] == "initialized"
        if initialized and (not target.is_file() or not ledger.is_file()):
            raise ValueError("recovery journal/snapshot missing; cannot recreate prior session")
        expected = legacy_snapshot(package["universe"])
        expected.update(accepted_package_sha256=sha(canonical(package)),
                        strategy_id=package["strategy_id"], strategy_version=package["version"],
                        package_deadline=package["deadline"], package_safety_limits=package["safety_limits"])
        if target.exists():
            metadata = json.loads(target.read_text())
            # The original revision remains provenance; content hashes are checked.
            if {k: v for k, v in metadata.items() if k != "code_revision"} != {k: v for k, v in expected.items() if k != "code_revision"}:
                raise ValueError("runtime package snapshot mismatch")
        else:
            if ledger.exists():
                raise ValueError("orphan journal without runtime snapshot")
            metadata = expected
            write_json(target, metadata)
        if ledger.exists():
            # Existing-file-only mode permits SQLite hot-journal rollback after
            # process loss. The owning supervisor holds the exclusive root lock.
            db = sqlite3.connect(ledger.resolve().as_uri() + "?mode=rw", uri=True)
            try:
                if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("recovery journal integrity failure")
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                rows = db.execute("SELECT body FROM state WHERE id=1").fetchall() if "state" in tables else []
                if rows and (len(rows) != 1 or json.loads(rows[0][0])["metadata"] != metadata):
                    raise ValueError("recovery journal state missing or mismatched")
                if initialized and (not rows or "events" not in tables):
                    raise ValueError("recovery journal state missing or mismatched")
                if "events" in tables:
                    events = db.execute("SELECT event_key,kind,payload FROM events LIMIT 1").fetchall()
                    if events and not rows:
                        raise ValueError("journal events without state")
            finally:
                db.close()
        if metadata["code_hash"] != package["hashes"]["code_sha256"]:
            raise ValueError("approved/runtime code hash mismatch")
        engine = PackageEngine(self.path, metadata, package, self.should_stop)
        try:
            # No strategy loop or entry may execute before this durable barrier.
            write_json(phase_path, dict(package_sha256=binding, phase="initialized"))
            engine.run(run_forever=True)
        finally:
            engine.close()
        return saved_state_report(self.path)
