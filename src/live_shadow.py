"""Strategy-free public shadow foundation with transactional checkpoints."""
from __future__ import annotations

import fcntl
import hashlib
import http.client
import json
import sqlite3
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode

from .binance_shadow_data import DataUnavailable, PublicShadowClient
from .live_paper_storage import ShadowJournal
from .research_session_manager import ResearchSessionManager
from .runtime_status import _STATUS_FILE_LOCK
from .shadow_execution import ShadowExecution, StandardShadowExecution, number


RULES = {"version": "shadow_foundation_v1", "fee_rate": "0.0005",
         "execution_penalty": "0.0005", "max_quote_age_ms": 5000,
         "leverage": 1, "fills": "sampled_top_of_book_model_not_exchange_fills",
         "funding": "quantity_immediately_before_event_times_exact_mark_and_rate",
         "strategies": [], "private_api": False, "real_orders": False,
         "testnet_orders": False}


def new_snapshot(symbols, initial_balance="1000"):
    if not symbols or len(set(symbols)) != len(symbols) or any(not s.isalnum() or not s.endswith("USDT") for s in symbols):
        raise ValueError("explicit unique USDT symbols required")
    if number(initial_balance) <= 0:
        raise ValueError("invalid initial collateral")
    root = Path(__file__).resolve().parent.parent
    code = hashlib.sha256()
    for name in ("live_shadow.py", "shadow_execution.py", "binance_shadow_data.py", "live_paper_storage.py"):
        code.update(name.encode())
        code.update((root / "src" / name).read_bytes())
    from .cloud_release import enabled, verify_release
    if enabled() or (root / "release-manifest.json").is_file():
        revision = verify_release(root)["revision"]
    else:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    return dict(engine_mode="live_shadow_v1", candidate_source="none",
                candidate_source_version=RULES["version"], configured_symbols=symbols,
                symbols=symbols, initial_balance=str(number(initial_balance)),
                rules=RULES, rules_version=RULES["version"],
                rules_hash=hashlib.sha256(ShadowJournal.encode(RULES).encode()).hexdigest(),
                code_revision=revision, code_hash=code.hexdigest(),
                fee_rate=RULES["fee_rate"], execution_penalty=RULES["execution_penalty"],
                max_quote_age_ms=RULES["max_quote_age_ms"],
                safety={"paper_only": True, "real_orders": False, "testnet_orders": False,
                        "private_api": False, "orders_sent": False})


class LiveShadowEngine:
    engine_mode = "live_shadow_v1"
    snapshot_factory = staticmethod(new_snapshot)
    execution_factory = ShadowExecution

    def __init__(self, data_root, metadata=None, client=None, status_store=None,
                 session_id=None, session_manager=None):
        self.root = Path(data_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / "shadow.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.lock.close()
            raise
        try:
            if metadata is None:
                metadata = json.loads((self.root / "config_snapshot.json").read_text())
            if metadata.get("engine_mode") != self.engine_mode:
                raise ValueError("not a shadow session")
            expected = self.snapshot_factory(metadata["symbols"], metadata["initial_balance"])
            for field in ("rules", "rules_hash", "rules_version", "code_hash", "fee_rate", "execution_penalty", "max_quote_age_ms"):
                if metadata[field] != expected[field]:
                    raise ValueError("shadow snapshot/runtime mismatch: " + field)
            for field in ("fixed_notional_usdt", "latency_ms", "funding_poll_interval_ms"):
                if field in expected and metadata.get(field) != expected[field]:
                    raise ValueError("shadow execution snapshot mismatch: " + field)
            self.journal = ShadowJournal(self.root / "shadow.sqlite3", metadata)
            self.execution = self.execution_factory(self.journal)
            self.client = client or PublicShadowClient()
            self.status_store = status_store
            self.session_id = session_id
            self.manager = session_manager
            self.closed = False
            self.invalidate("process_start", gap=True)
        except BaseException:
            if hasattr(self, "journal"):
                self.journal.close()
            self.lock.close()
            raise

    def invalidate(self, reason, symbol=None, gap=False):
        payload = {"reason": reason, "symbol": symbol, "gap": gap}
        def apply(state):
            symbols = [symbol] if symbol else state["metadata"]["symbols"]
            for item in symbols:
                state["health"][item] = {"ready": False, "reason": reason}
            if gap:
                for position in state["positions"].values():
                    if position["symbol"] in symbols:
                        position["gap_exposure"] = True
        self.journal.transact("health:" + uuid.uuid4().hex, "health", payload, apply)

    def _append_trades(self, symbol, rows, bootstrap=False):
        if not rows:
            raise DataUnavailable("empty trades page")
        def apply(state):
            market = state["market"].setdefault(symbol, {})
            last = market.get("last_id")
            last_ms = market.get("last_trade_ms", 0)
            for row in rows:
                current = int(row["a"])
                if last is not None and current != last + 1:
                    raise DataUnavailable("noncontiguous aggregate trade IDs")
                if int(row["T"]) < last_ms or number(row["p"]) <= 0 or number(row["q"]) <= 0:
                    raise DataUnavailable("invalid trade values/order")
                last, last_ms = current, int(row["T"])
            if bootstrap:
                market["coverage_start_ms"] = int(rows[0]["T"])
                market["funding_checked_ms"] = int(rows[0]["T"])
            market.update(last_id=last, last_trade_ms=last_ms)
        self.journal.transact(f"trades:{symbol}:{rows[0]['a']}:{rows[-1]['a']}",
                              "public_trades", {"symbol": symbol, "rows": rows}, apply)

    def poll_once(self, max_pages=10, symbols=None):
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        # Persistent fail-closed before any network request, including after restart.
        configured = self.journal.read()["metadata"]["symbols"]
        selected = configured if symbols is None else symbols
        if not set(selected) <= set(configured):
            raise ValueError("poll outside session universe")
        if symbols is None:
            self.invalidate("poll_in_progress")
        for symbol in selected:
            self.invalidate("poll_in_progress", symbol=symbol)
            try:
                head_rows = self.client.trades(symbol, limit=1)
                if not head_rows:
                    raise DataUnavailable("empty live head")
                head = int(head_rows[-1]["a"])
                market = self.journal.read()["market"].get(symbol, {})
                if "last_id" not in market:
                    self._append_trades(symbol, head_rows[-1:], bootstrap=True)
                else:
                    if head < market["last_id"]:
                        raise DataUnavailable("source head behind checkpoint")
                    for _ in range(max_pages):
                        last = self.journal.read()["market"][symbol]["last_id"]
                        if last >= head:
                            break
                        rows = self.client.trades(symbol, from_id=last + 1, limit=min(1000, head - last))
                        rows = [row for row in rows if int(row["a"]) <= head]
                        self._append_trades(symbol, rows)
                    if self.journal.read()["market"][symbol]["last_id"] < head:
                        raise DataUnavailable("backfill page budget exhausted")
                market = self.journal.read()["market"][symbol]
                now = self.client.server_time()
                start = market["coverage_start_ms"]
                funding_interval = self.journal.read()["metadata"].get("funding_poll_interval_ms", 0)
                funding_polled = now - market.get("funding_last_request_ms", 0) >= funding_interval
                if funding_polled:
                    for event in self.client.funding(symbol, start, now):
                        self.execution.funding(event)
                quote = self.client.quote(symbol)
                now = self.client.server_time()
                if quote["symbol"] != symbol or not 0 <= now - int(quote["time"]) <= RULES["max_quote_age_ms"]:
                    raise DataUnavailable("stale/future/mismatched quote")
                bid, ask = number(quote["bidPrice"]), number(quote["askPrice"])
                if not 0 < bid <= ask or min(number(quote["bidQty"]), number(quote["askQty"])) <= 0:
                    raise DataUnavailable("invalid quote")
                def ready(state):
                    old = state["market"][symbol].get("quote")
                    if old and quote.get("lastUpdateId", 0) < old.get("lastUpdateId", 0):
                        raise DataUnavailable("quote update ID regressed")
                    if old and int(quote["time"]) < int(old["time"]):
                        raise DataUnavailable("quote timestamp regressed")
                    if old and int(quote["time"]) - int(old["time"]) > RULES["max_quote_age_ms"]:
                        for position in state["positions"].values():
                            if position["symbol"] == symbol:
                                position["gap_exposure"] = True
                    state["market"][symbol].update(quote=quote, funding_checked_ms=now)
                    if funding_polled:
                        state["market"][symbol]["funding_last_request_ms"] = now
                    state["health"][symbol] = {"ready": True, "reason": None,
                                              "checked_ms": now, "trade_head": head,
                                              "historical_quote_backfill": False}
                self.journal.transact("quote:" + uuid.uuid4().hex, "public_quote",
                                      {"symbol": symbol, "quote": quote, "now_ms": now}, ready)
            except DataUnavailable as exc:
                self.invalidate(str(exc), symbol=symbol, gap=True)
            # Persistence/accounting/schema exceptions deliberately escape the symbol loop.
        return self.journal.read()["health"]

    def publish_status(self):
        state = self.journal.read()
        payload = dict(candidate_source=state["metadata"]["candidate_source"],
                       candidate_source_version=state["metadata"]["candidate_source_version"],
                       shadow_mode=True, shadow_journal_path=str(self.journal.path),
                       shadow_signal_count=len(state["signals"]),
                       shadow_pending_count=len(set(state["signals"]) - set(state["positions"]) - set(state["closed"])),
                       shadow_execution_wait=state.get("execution_wait", {}),
                       legacy_scan_report=state.get("legacy_scan_report", {}),
                       shadow_heartbeat_ms=int(time.time() * 1000),
                       open_positions_current=len(state["positions"]),
                       open_positions_count=len(state["positions"]),
                       closed_trades_count=len(state["closed"]),
                       shadow_health=state["health"], shadow_accounting=self.execution.accounting(),
                       safety_status=state["metadata"]["safety"])
        if self.status_store:
            self.status_store.update(**payload)
        if self.manager and self.session_id:
            self.manager.session_status_store(self.session_id).update(**payload)
        return payload

    def run(self, max_iterations=1, interval_sec=1, run_forever=False, **_unused):
        if max_iterations < 1 or interval_sec < 0:
            raise ValueError("invalid bounded run")
        reason = "bounded_shadow_complete"
        try:
            count = 0
            while run_forever or count < max_iterations:
                if self.status_store:
                    control = self.status_store.read().get("control_state")
                    if control not in {"start_requested", "running"}:
                        reason = "operator_stop_or_restart_request"
                        break
                    with _STATUS_FILE_LOCK:
                        if self.status_store.read().get("control_state") == "start_requested":
                            self.status_store.update(control_state="running")
                        elif self.status_store.read().get("control_state") != "running":
                            reason = "operator_stop_or_restart_request"
                            break
                self.poll_once()
                self.publish_status()
                count += 1
                if run_forever or count < max_iterations:
                    deadline = time.monotonic() + interval_sec
                    while time.monotonic() < deadline:
                        if self.status_store and self.status_store.read().get("control_state") not in {"start_requested", "running"}:
                            break
                        time.sleep(min(1, max(0, deadline - time.monotonic())))
            self.invalidate("stopped")
            self.publish_status()
            if self.manager and self.session_id:
                self.manager.finalize_session(self.session_id, stop_reason=reason,
                    unresolved_open_positions_count=len(self.journal.read()["positions"]), latest_report_path=None)
        except BaseException as exc:
            if self.manager and self.session_id:
                try:
                    self.manager.finalize_failed_session_best_effort(self.session_id,
                        stop_reason="shadow_interrupted", error=type(exc).__name__,
                        unresolved_open_positions_count=len(self.journal.read()["positions"]), latest_report_path=None)
                except (OSError, RuntimeError):
                    pass
            raise
        finally:
            self.close()

    def close(self):
        if not self.closed:
            self.journal.close()
            self.lock.close()
            self.closed = True


def run_shadow_command(data_root, symbols, max_iterations=1, resume_session=None):
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")
    root = Path(data_root).resolve()
    if not resume_session and root.exists() and any(root.iterdir()):
        raise ValueError("new shadow run requires a new empty data root")
    manager = ResearchSessionManager(root)
    manager.ensure_initialized()
    if resume_session:
        status = manager.global_status_store.read()
        if status.get("active_session_id") != resume_session or status.get("control_state") not in {"running", "start_requested"}:
            raise ValueError("only the active interrupted shadow session can resume")
        session_id = resume_session
        paths = manager.paths(session_id)
    else:
        session_id, paths = manager.create_session(new_snapshot(symbols))
        manager.mark_start_requested(session_id)
    engine = LiveShadowEngine(paths.root, status_store=manager.global_status_store,
                              session_id=session_id, session_manager=manager)
    engine.run(max_iterations=max_iterations)
    return {"session_id": session_id, "data_root": str(paths.root),
            "journal": str(paths.root / "shadow.sqlite3"), "strategies": []}


def finalize_shadow_failure(manager, session_id, error):
    """Never interpret empty legacy CSVs as evidence of no shadow positions."""
    path = manager.paths(session_id).root / "shadow.sqlite3"
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            state = json.loads(db.execute("SELECT body FROM state WHERE id=1").fetchone()[0])
            count = len(state["positions"])
        finally:
            db.close()
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        # Keep the session identity for operator recovery; unknown is not zero.
        for store in (manager.session_status_store(session_id), manager.global_status_store):
            try:
                store.update(control_state="stopped", status="interrupted",
                             live_engine_enabled=False, unresolved_open_positions_count=None,
                             shadow_storage_error=error, shadow_accounting_status="UNKNOWN")
            except OSError:
                pass
        return
    manager.finalize_failed_session_best_effort(
        session_id, stop_reason="shadow_interrupted", error=error,
        unresolved_open_positions_count=count, latest_report_path=None)


def legacy_snapshot(symbols=None, initial_balance="1000"):
    from .legacy_crypto13_shadow import ARCHIVE_SHA256, SOURCE_SHA256, SYMBOLS, SIGNAL_OPTIONS

    if symbols is not None and list(symbols) != list(SYMBOLS):
        raise ValueError("legacy universe override forbidden")
    result = new_snapshot(list(SYMBOLS), initial_balance)
    rules = dict(version="legacy_auto_archive_v1", archive_sha256=ARCHIVE_SHA256,
                 source_sha256=SOURCE_SHA256, symbols=list(SYMBOLS), timeframe="1h", htf="4h",
                 signal_options=SIGNAL_OPTIONS, auto_interval_sec=90, auto_limit=3,
                 cooldown_sec=120, dedup_sec=21600, unclosed_candles=True,
                 execution="STANDARD_SHADOW_EXECUTION", fixed_notional_usdt="100",
                 latency_ms=1000, fee_rate="0.0005", execution_penalty="0.0005",
                 max_quote_age_ms=5000, leverage=1,
                 initial_balance=str(number(initial_balance)),
                 triggers="observed_bid_long_ask_short_at_unchanged_source_levels",
                 gaps="no_historical_quote_reconstruction; first_touch_unverified",
                 funding="exact_public_event_mark_times_quantity_before_event",
                 funding_poll_interval_ms=60000,
                 admission="durable_signal_record_replaces_successful_telegram_delivery")
    code = hashlib.sha256(result["code_hash"].encode())
    for name in ("legacy_crypto13_shadow.py", "legacy_crypto13_snapshot/signals.py"):
        code.update(name.encode())
        code.update((Path(__file__).parent / name).read_bytes())
    result.update(engine_mode="legacy_crypto13_shadow_v1", candidate_source="legacy_crypto13_auto",
                  candidate_source_version=rules["version"], rules=rules,
                  rules_version=rules["version"], rules_hash=hashlib.sha256(ShadowJournal.encode(rules).encode()).hexdigest(),
                  code_hash=code.hexdigest(), fixed_notional_usdt="100", latency_ms=1000,
                  funding_poll_interval_ms=60000)
    return result


def legacy_public_get(path, params, timeout):
    """Only the archived signal source's public klines route, no credentials."""
    from .legacy_crypto13_shadow import SYMBOLS

    if (path != "/fapi/v1/klines" or set(params) != {"symbol", "interval", "limit"}
            or params["symbol"] not in SYMBOLS or params["interval"] not in {"1h", "4h"}
            or params["limit"] != 200):
        raise DataUnavailable("disallowed legacy public route")
    connection = http.client.HTTPSConnection("fapi.binance.com", timeout=min(10, timeout))
    try:
        connection.request("GET", path + "?" + urlencode(params), headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise DataUnavailable("oversized legacy public response")
        return response.status, body
    finally:
        connection.close()


class LegacyShadowEngine(LiveShadowEngine):
    engine_mode = "legacy_crypto13_shadow_v1"
    snapshot_factory = staticmethod(legacy_snapshot)
    execution_factory = StandardShadowExecution

    def __init__(self, *args, adapter=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .legacy_crypto13_shadow import LegacySignalAdapter

        self.stop_requested = False
        self.adapter = adapter or LegacySignalAdapter(legacy_public_get, cancelled=self._should_stop)
        saved = self.journal.read().get("legacy_adapter")
        if saved:
            self.adapter.restore_state(saved)
        # A durable signal is the admission commit point, even if the following
        # cache/cooldown checkpoint was interrupted before acknowledgement.
        sent = self.adapter.dump_state()["last_sent"]
        for signal in self.journal.read()["signals"].values():
            admitted = signal["context"].get("admission_local_ms", signal["decision_ms"])
            if admitted > sent.get(signal["symbol"], -1):
                self.adapter.mark_sent(signal["symbol"], admitted)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.scan_future = None
        self.completed_scans = 0

    def _should_stop(self):
        return self.stop_requested or (self.status_store is not None and
            self.status_store.read().get("control_state") not in {"start_requested", "running"})

    def _save_adapter(self, next_scan_ms, admission_complete=False):
        payload = dict(adapter=self.adapter.dump_state(), next_scan_ms=next_scan_ms,
                       scan_report=getattr(self.adapter, "last_scan_report", {}))
        def apply(state):
            state["legacy_adapter"] = payload["adapter"]
            state["next_scan_ms"] = next_scan_ms
            state["legacy_scan_report"] = payload["scan_report"]
            if admission_complete:
                state.pop("legacy_admission", None)
        self.journal.transact("legacy_state:" + uuid.uuid4().hex, "legacy_checkpoint", payload, apply)

    def _admit(self, selected):
        if "legacy_admission" not in self.journal.read():
            payload = dict(selected=selected, adapter=self.adapter.dump_state())
            def begin(state):
                state["legacy_admission"] = payload
                state["legacy_adapter"] = payload["adapter"]
            self.journal.transact("admission:" + uuid.uuid4().hex, "legacy_admission_batch", payload, begin)
        sent = 0
        for signal in selected:
            if self._should_stop():
                return
            # Decision/context are durable before any attempt to obtain a fill.
            signal_id = signal["signal_id"]
            state = self.journal.read()
            if signal_id in state["signals"]:
                # Recover a crash between durable admission and adapter checkpoint.
                saved = state["signals"][signal_id]
                self.adapter.mark_sent(signal["symbol"], saved["context"]["admission_local_ms"])
                sent += 1
                continue
            try:
                stamp = self.client.server_time()
            except DataUnavailable:
                return  # Durable batch remains pending, not a guessed execution time.
            local_stamp = int(time.time() * 1000)
            context = dict(signal["context"])
            context.update(source_context_local_as_of_ms=context["as_of_ms"],
                           as_of_ms=stamp, admission_local_ms=local_stamp,
                           decision_time_source="binance_server_after_source_generation",
                           source_signal={k: v for k, v in signal.items() if k != "context"},
                           source_levels=dict(entry_reference=signal["entry"], tp=signal["tp"], sl=signal["sl"]))
            side = signal["direction"].upper()
            self.execution.record_signal(signal_id, signal["symbol"], side, None, stamp, context)
            self.adapter.mark_sent(signal["symbol"], local_stamp)
            sent += 1
            self._save_adapter(local_stamp + 90000)
            time.sleep(0.4)
        self.adapter.finish_scan(sent)
        self._save_adapter(int(time.time() * 1000) + 90000, admission_complete=True)

    def _advance_symbol(self, symbol):
        state = self.journal.read()
        if not state["health"].get(symbol, {}).get("ready"):
            return
        try:
            now = self.client.server_time()
        except DataUnavailable as exc:
            self.invalidate(str(exc), symbol=symbol, gap=True)
            return
        if abs(now - int(time.time() * 1000)) > 1000:
            self.invalidate("local_exchange_clock_skew", symbol=symbol, gap=True)
            return
        # Observe exits before new entries; paper collateral is never infinite.
        for signal_id, position in list(state["positions"].items()):
            if self._should_stop():
                return
            if position["symbol"] != symbol:
                continue
            try:
                self.execution.request_exit(signal_id, now)
                if signal_id in self.journal.read().get("exit_intents", {}):
                    self.execution.exit(signal_id, now)
            except ValueError as exc:
                self._execution_wait(signal_id, str(exc))
        state = self.journal.read()
        for signal_id, signal in state["signals"].items():
            if self._should_stop():
                return
            if signal["symbol"] != symbol or signal_id in state["positions"] or signal_id in state["closed"]:
                continue
            try:
                self.execution.enter(signal_id, now)
            except ValueError as exc:
                self._execution_wait(signal_id, str(exc))

    def _execution_wait(self, signal_id, reason):
        # Append only when the reason changes, not once per polling loop.
        if self.journal.read().get("execution_wait", {}).get(signal_id) == reason:
            return
        def apply(state):
            state.setdefault("execution_wait", {})[signal_id] = reason
        self.journal.transact("execution_wait:" + uuid.uuid4().hex, "execution_wait",
                              dict(signal_id=signal_id, reason=reason), apply)

    def run(self, max_iterations=1, interval_sec=1, run_forever=False, **_unused):
        if max_iterations < 1:
            raise ValueError("positive scan limit required")
        reason = "bounded_legacy_shadow_complete"
        drain_until = None
        try:
            while True:
                if self.stop_requested:
                    reason = "operator_stop"
                    break
                if self.status_store:
                    with _STATUS_FILE_LOCK:
                        control = self.status_store.read().get("control_state")
                        if control not in {"start_requested", "running"}:
                            reason = "operator_stop"
                            break
                        if control == "start_requested":
                            self.status_store.update(control_state="running", live_engine_enabled=True)
                state = self.journal.read()
                now = int(time.time() * 1000)
                if state.get("legacy_admission") is not None:
                    self._admit(state["legacy_admission"]["selected"])
                    state = self.journal.read()
                if self.scan_future is None and not state.get("legacy_admission") and (run_forever or self.completed_scans < max_iterations):
                    if now >= state.get("next_scan_ms", 0):
                        if now < self.adapter.dump_state()["cooldown_until_ms"]:
                            self._save_adapter(now + 20000)
                        else:
                            self.scan_future = self.pool.submit(self.adapter.scan)
                if self.scan_future is not None and self.scan_future.done():
                    from .legacy_crypto13_shadow import ScanUnavailable

                    try:
                        selected = self.scan_future.result()
                    except ScanUnavailable:
                        self._save_adapter(now + 10000)
                    else:
                        if not self._should_stop():
                            self._admit(selected)
                    self.completed_scans += 1
                    self.scan_future = None
                state = self.journal.read()
                watch = sorted({s["symbol"] for s in state["signals"].values()})
                for symbol in watch:
                    if self._should_stop():
                        break
                    self.poll_once(symbols=[symbol])
                    self._advance_symbol(symbol)
                self.publish_status()
                if not run_forever and self.completed_scans >= max_iterations:
                    state = self.journal.read()
                    pending = set(state["signals"]) - set(state["positions"]) - set(state["closed"])
                    if not pending and not state.get("legacy_admission"):
                        break
                    if drain_until is None:
                        drain_until = time.monotonic() + 15
                    if time.monotonic() >= drain_until:
                        reason = "bounded_legacy_shadow_pending_unfilled"
                        break
                time.sleep(1)
            self.stop_requested = True
            self.pool.shutdown(wait=True)
            self.invalidate("stopped")
            self.publish_status()
            if self.manager and self.session_id:
                self.manager.finalize_session(self.session_id, stop_reason=reason,
                    unresolved_open_positions_count=len(self.journal.read()["positions"]), latest_report_path=None)
        except BaseException as exc:
            self.stop_requested = True
            self.pool.shutdown(wait=True)
            if self.manager and self.session_id:
                finalize_shadow_failure(self.manager, self.session_id, type(exc).__name__)
            raise
        finally:
            self.close()

    def close(self):
        self.stop_requested = True
        if hasattr(self, "pool"):
            self.pool.shutdown(wait=True)
        super().close()


def run_legacy_shadow_command(data_root, max_iterations=1, run_forever=False, resume_session=None):
    root = Path(data_root).resolve()
    if not resume_session and root.exists() and any(root.iterdir()):
        raise ValueError("legacy shadow requires a new isolated empty root")
    manager = ResearchSessionManager(root)
    manager.ensure_initialized()
    if resume_session:
        status = manager.global_status_store.read()
        if status.get("active_session_id") != resume_session or status.get("control_state") not in {"running", "start_requested"}:
            raise ValueError("only the active interrupted legacy session can resume")
        session_id, paths = resume_session, manager.paths(resume_session)
    else:
        session_id, paths = manager.create_session(legacy_snapshot())
        manager.mark_start_requested(session_id)
    engine = LegacyShadowEngine(paths.root, status_store=manager.global_status_store,
                                session_id=session_id, session_manager=manager)
    import signal
    import threading

    previous = {}
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda *_: setattr(engine, "stop_requested", True))
    try:
        engine.run(max_iterations=max_iterations, run_forever=run_forever)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return {"session_id": session_id, "journal": str(paths.root / "shadow.sqlite3")}
