"""Declarative, local package registry. Never imports or starts an adapter."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3


ADAPTER = "legacy_crypto13_auto_v1"
SYNTHETIC_ADAPTER = "synthetic_noop_v1"
MAX_BYTES = 131072
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
CODE_FILES = ("live_shadow.py", "shadow_execution.py", "binance_shadow_data.py", "live_paper_storage.py")
LEGACY_FILES = ("legacy_crypto13_shadow.py", "legacy_crypto13_snapshot/signals.py")
SYNTHETIC_CODE_FILES = ("strategy_packages.py", "package_shadow_runtime.py")


class PackageError(ValueError):
    pass


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise PackageError("Invalid JSON value") from exc


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise PackageError("Invalid strategy_id/version")
    return value


def parse(raw):
    if not isinstance(raw, (bytes, str)):
        raise PackageError("Package must be UTF-8 JSON, not code or an archive")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PackageError("Duplicate JSON key")
            result[key] = value
        return result
    try:
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(data) > MAX_BYTES:
            raise PackageError("Package exceeds size limit")
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(PackageError("Non-finite JSON")))
        if not isinstance(value, dict):
            raise PackageError("Package must be an object")
        identifier(value.get("strategy_id"))
        identifier(value.get("version"))
        canonical(value)
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise PackageError(str(exc)) from exc


def _trusted_constants():
    # Only parse local allowlisted source literals. No eval, imports or user paths.
    tree = ast.parse(Path(__file__).with_name("legacy_crypto13_shadow.py").read_text())
    wanted = {"ARCHIVE_SHA256", "SOURCE_SHA256", "SYMBOLS", "SIGNAL_OPTIONS", "RULES"}
    values = {}
    def literal(node):
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict" and not node.args:
            result = {}
            for keyword in node.keywords:
                if keyword.arg is None:
                    result.update(literal(keyword.value))
                else:
                    result[keyword.arg] = literal(keyword.value)
            return result
        return ast.literal_eval(node)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in wanted:
                values[name] = literal(node.value)
    if set(values) != wanted:
        raise PackageError("Local adapter contract incomplete")
    return values


def contract(adapter=ADAPTER):
    """Return a fresh detached declaration for one explicitly allowlisted adapter."""
    if adapter == SYNTHETIC_ADAPTER:
        base = Path(__file__).parent
        rules = dict(
            parameters=dict(mode="diagnostic_noop", poll_interval_ms=100),
            universe=[],
            execution_model=dict(
                name="SYNTHETIC_NOOP",
                market_data=False,
                fills=False,
                positions=False,
                orders=False,
                private_api=False,
            ),
            data_requirements=dict(venue="NONE", market_data=False, private_api=False),
        )
        code = hashlib.sha256()
        for name in SYNTHETIC_CODE_FILES:
            code.update(name.encode())
            code.update((base / name).read_bytes())
        return rules, {"rules_sha256": sha(canonical(rules)), "code_sha256": code.hexdigest()}
    if adapter != ADAPTER:
        raise PackageError("Adapter not allowlisted")
    local = _trusted_constants()
    base = Path(__file__).parent
    if hashlib.sha256((base / LEGACY_FILES[1]).read_bytes()).hexdigest() != local["SOURCE_SHA256"]:
        raise PackageError("Immutable legacy source hash mismatch")
    code = hashlib.sha256()
    for name in CODE_FILES:
        code.update(name.encode())
        code.update((base / name).read_bytes())
    code = hashlib.sha256(code.hexdigest().encode())
    for name in LEGACY_FILES:
        code.update(name.encode())
        code.update((base / name).read_bytes())
    rules = dict(parameters=local["RULES"], universe=list(local["SYMBOLS"]),
                 execution_model=dict(name="STANDARD_SHADOW_EXECUTION", fixed_notional_usdt="100",
                                      latency_ms=1000, fee_rate="0.0005", adverse_slippage="0.0005",
                                      max_quote_age_ms=5000, leverage=1,
                                      funding="actual_public_event_mark_times_quantity_before_event",
                                      fills="model_bid_ask_not_exchange_fills"),
                 data_requirements=dict(venue="BINANCE_USDM", klines=["1h", "4h"],
                                        forming_candles=True, trades="aggTrades", quotes="bookTicker",
                                        funding=True, incomplete_data="block_new_entries"),
                 source_sha256=local["SOURCE_SHA256"], archive_sha256=local["ARCHIVE_SHA256"])
    return rules, {"rules_sha256": sha(canonical(rules)), "code_sha256": code.hexdigest()}


def example_package(strategy_id, version, deadline):
    rules, hashes = contract()
    return dict(schema_version=1, strategy_id=identifier(strategy_id), version=identifier(version),
                adapter=ADAPTER, frozen_parameters=rules["parameters"],
                execution_model=rules["execution_model"], universe=rules["universe"],
                data_requirements=rules["data_requirements"], deadline=deadline,
                safety_limits=dict(paper_only=True, private_api=False, real_orders=False,
                                   testnet_orders=False, max_open_positions=10, max_total_notional_usdt="1000"),
                hashes=hashes)


def synthetic_package(strategy_id, version, deadline):
    rules, hashes = contract(SYNTHETIC_ADAPTER)
    return dict(
        schema_version=1,
        strategy_id=identifier(strategy_id),
        version=identifier(version),
        adapter=SYNTHETIC_ADAPTER,
        frozen_parameters=rules["parameters"],
        execution_model=rules["execution_model"],
        universe=rules["universe"],
        data_requirements=rules["data_requirements"],
        deadline=deadline,
        safety_limits=dict(
            paper_only=True,
            private_api=False,
            real_orders=False,
            testnet_orders=False,
            max_open_positions=0,
            max_total_notional_usdt="0",
        ),
        hashes=hashes,
    )


def validate_package(raw, now=None):
    p = parse(raw)
    expected = {"schema_version", "strategy_id", "version", "adapter", "frozen_parameters", "execution_model",
                "universe", "data_requirements", "deadline", "safety_limits", "hashes"}
    if set(p) != expected or type(p["schema_version"]) is not int or p["schema_version"] != 1:
        raise PackageError("Unknown/missing fields or schema version")
    # Preserve the original no-argument legacy contract call for existing
    # integrity hooks; only diagnostic adapters use the explicit dispatcher.
    rules, hashes = contract() if p["adapter"] == ADAPTER else contract(p["adapter"])
    for field, key in [("frozen_parameters", "parameters"), ("execution_model", "execution_model"),
                       ("universe", "universe"), ("data_requirements", "data_requirements")]:
        if canonical(p[field]) != canonical(rules[key]):
            raise PackageError("Frozen contract mismatch: " + field)
    if p["hashes"] != hashes:
        raise PackageError("Rules/code hashes mismatch")
    limits = p["safety_limits"]
    if not isinstance(limits, dict) or set(limits) != {"paper_only", "private_api", "real_orders", "testnet_orders", "max_open_positions", "max_total_notional_usdt"}:
        raise PackageError("Invalid safety limits")
    for key, value in [("paper_only", True), ("private_api", False), ("real_orders", False), ("testnet_orders", False)]:
        if limits[key] is not value:
            raise PackageError("Unsafe execution flag")
    count = limits["max_open_positions"]
    if p["adapter"] == SYNTHETIC_ADAPTER:
        if type(count) is not int or count != 0 or limits["max_total_notional_usdt"] != "0":
            raise PackageError("Synthetic adapter forbids positions and notional")
    elif type(count) is not int or not 1 <= count <= 10 or limits["max_total_notional_usdt"] != str(count * 100):
        raise PackageError("Limits must cap 1..10 positions at fixed 100 USDT notional")
    try:
        end = datetime.fromisoformat(p["deadline"].replace("Z", "+00:00"))
        if end.tzinfo is None or end.utcoffset().total_seconds() != 0:
            raise ValueError()
        if end <= (now or datetime.now(timezone.utc)):
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        raise PackageError("Deadline must be a future absolute UTC timestamp") from None
    return p


class PackageStore:
    """Independent packages keyed by ID/version; approval does not start anything."""
    def __init__(self, path):
        from .cloud_release import schema_preflight, schema_check
        self.path = Path(path)
        tables = {"packages": "strategy_id version payload digest status snapshot snapshot_digest reason"}
        schema_preflight(self.path, tables)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        fresh = schema_check(self.db, tables)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS packages (strategy_id TEXT, version TEXT, payload TEXT NOT NULL, digest TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('uploaded','validated','approved','rejected')), snapshot TEXT, snapshot_digest TEXT, reason TEXT, PRIMARY KEY(strategy_id,version))")
        self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_package BEFORE UPDATE ON packages WHEN NEW.strategy_id IS NOT OLD.strategy_id OR NEW.version IS NOT OLD.version OR NEW.payload IS NOT OLD.payload OR NEW.digest IS NOT OLD.digest OR (OLD.snapshot IS NOT NULL AND (NEW.snapshot IS NOT OLD.snapshot OR NEW.snapshot_digest IS NOT OLD.snapshot_digest)) BEGIN SELECT RAISE(ABORT,'immutable package'); END")
        self.db.execute("CREATE TRIGGER IF NOT EXISTS no_package_delete BEFORE DELETE ON packages BEGIN SELECT RAISE(ABORT,'immutable package'); END")
        self.db.execute("CREATE TRIGGER IF NOT EXISTS package_transition BEFORE UPDATE OF status ON packages WHEN NOT ((OLD.status='uploaded' AND NEW.status IN ('validated','rejected')) OR (OLD.status='validated' AND NEW.status IN ('approved','rejected'))) BEGIN SELECT RAISE(ABORT,'invalid transition'); END")
        if fresh:
            self.db.execute("PRAGMA user_version=1")

    def close(self):
        self.db.close()

    def list_packages(self):
        """Deterministic inventory; no implicit selected/active package."""
        keys = self.db.execute("SELECT strategy_id,version FROM packages ORDER BY strategy_id,version").fetchall()
        return [self.get(strategy_id, version) for strategy_id, version in keys]

    def upload(self, raw):
        p = parse(raw)
        text = canonical(p)
        try:
            self.db.execute("INSERT INTO packages(strategy_id,version,payload,digest,status) VALUES (?,?,?,?,'uploaded')",
                            (p["strategy_id"], p["version"], text, sha(text)))
        except sqlite3.IntegrityError as exc:
            raise PackageError("Duplicate ID/version; existing package not replaced") from exc
        return self.get(p["strategy_id"], p["version"])

    def get(self, strategy_id, version):
        row = self.db.execute("SELECT payload,digest,status,snapshot,snapshot_digest,reason FROM packages WHERE strategy_id=? AND version=?",
                              (identifier(strategy_id), identifier(version))).fetchone()
        if row is None:
            raise PackageError("Unknown package")
        payload, digest, status, snapshot, snapshot_digest, reason = row
        p = parse(payload)
        if sha(payload) != digest or (p["strategy_id"], p["version"]) != (strategy_id, version):
            raise PackageError("Stored package tampered")
        if snapshot is not None and (snapshot != payload or sha(snapshot) != snapshot_digest):
            raise PackageError("Accepted snapshot tampered")
        if status in {"validated", "approved"} and snapshot is None:
            raise PackageError("Accepted snapshot missing")
        return dict(package=p, status=status, snapshot=parse(snapshot) if snapshot is not None else None,
                    package_sha256=digest, reason=reason)

    def _transition(self, strategy_id, version, target, now=None, reason=None):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            current = self.get(strategy_id, version)
            allowed = {"validated": {"uploaded"}, "approved": {"validated"}, "rejected": {"uploaded", "validated"}}
            if current["status"] not in allowed[target]:
                raise PackageError("Invalid transition")
            if target != "rejected":
                validate_package(canonical(current["package"]), now)
            if target == "validated":
                text = canonical(current["package"])
                self.db.execute("UPDATE packages SET status=?,snapshot=?,snapshot_digest=? WHERE strategy_id=? AND version=?",
                                (target, text, sha(text), strategy_id, version))
            else:
                self.db.execute("UPDATE packages SET status=?,reason=? WHERE strategy_id=? AND version=?", (target, reason, strategy_id, version))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self.get(strategy_id, version)

    def validate(self, strategy_id, version, now=None):
        return self._transition(strategy_id, version, "validated", now)

    def approve(self, strategy_id, version, now=None):
        return self._transition(strategy_id, version, "approved", now)

    def reject(self, strategy_id, version, reason):
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
            raise PackageError("Rejection reason required (max 1000 characters)")
        return self._transition(strategy_id, version, "rejected", reason=reason)
