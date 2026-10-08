"""Archive Auto signal adapter only; no execution, persistence IO or live launch.

API: LegacySignalAdapter(transport=None, *, clock_ms=None, sleep=time.sleep,
                         cancelled=None).
scan() is synchronous and returns a list. If no symbol could be evaluated it
raises ScanUnavailable; last_scan_report distinguishes ok/partial/unavailable/
cooldown/cancelled and includes symbol-level errors without raw exception messages.
cancelled() is checked before each batch and after all its futures complete;
if true, scan raises ScanUnavailable('cancelled') without accepting that batch
or starting another. Inflight original signal calls are allowed to finish.
transport(path, params, timeout) -> (HTTP status, JSON bytes) MUST be GET-only,
credential-free, fixed to fapi.binance.com, and must not follow redirects.
The default transport uses direct HTTPS, no netrc, env proxies or redirects.
clock_ms returns Unix ms;
sleep takes seconds and covers both batch pauses and original retry backoffs.

scan returns at most three original Signal dictionaries plus context. Context
contains the exact public cached/unclosed klines used, with observation times;
no supplemental requests are issued. After each successful shadow admission call
mark_sent(symbol, now_ms), then finish_scan(sent_count) once after all admissions.
No automatic marking: failed admissions must not consume dedup or cooldown.
dump_state/restore_state exchange JSON-compatible cache/dedup/cooldown state.
The caller owns persistence, cadence (original Auto: 90s), and serialization
of calls to this adapter. One instance represents one original Auto chat (1h).
"""

from __future__ import annotations

import builtins
import copy
import hashlib
import json
import http.client
import sys
import time
import uuid
import threading
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pandas as pd
import requests

ARCHIVE_SHA256 = "b7a3fa3b9eafdaf289396c1ea5937b894d55789c071a5649159c56a9f8cc7217"
SOURCE_SHA256 = "280942d2265b8f43aa5d1d66cc6c633f2212b8cb0cb4c1ffe7f0453e009ec624"
SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "TRXUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT",
    "ATOMUSDT", "BCHUSDT", "ETCUSDT", "XLMUSDT", "ARBUSDT", "OPUSDT",
    "MATICUSDT", "POLUSDT", "APTUSDT", "SUIUSDT", "NEARUSDT", "INJUSDT",
    "UNIUSDT", "AAVEUSDT", "CRVUSDT", "SNXUSDT", "DYDXUSDT", "GMXUSDT",
    "RNDRUSDT", "FETUSDT", "AGIXUSDT", "GRTUSDT", "FILUSDT", "ICPUSDT",
    "IMXUSDT", "STXUSDT", "RUNEUSDT", "KASUSDT", "ORDIUSDT", "TIAUSDT",
    "SEIUSDT", "FTMUSDT", "ENAUSDT", "JUPUSDT",
)
SIGNAL_OPTIONS = dict(min_score=85, vol_mult=0.95, red_threshold=0,
                      allow_trend_fallback=True)
RULES = dict(timeframe="1h", trend_timeframe="4h", **SIGNAL_OPTIONS,
             max_selected=3, batch_size=5, batch_pause_seconds=0.7,
             dedup_ms=21600000, cooldown_ms=120000, auto_interval_seconds=90,
             cooldown_poll_seconds=20, tp_r_mult=1.5, sl_r_mult=1.0,
             unclosed_candles=True)
RULES_FINGERPRINT = hashlib.sha256(json.dumps(
    dict(rules=RULES, symbols=SYMBOLS, source_sha256=SOURCE_SHA256),
    sort_keys=True, separators=(",", ":"),
).encode()).hexdigest()
_ROUTES = {
    "/fapi/v1/klines": {"symbol", "interval", "limit"},
}


class ScanUnavailable(RuntimeError):
    """No symbol could be evaluated; inspect adapter.last_scan_report."""


def _public_get(path, params, timeout):
    if path not in _ROUTES or set(params) != _ROUTES[path]:
        raise ValueError("Disallowed public route")
    connection = http.client.HTTPSConnection("fapi.binance.com", timeout=timeout)
    try:
        connection.request("GET", path + "?" + urlencode(params),
                           headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Oversized public response")
        return response.status, body
    finally:
        connection.close()


class LegacySignalAdapter:
    def __init__(self, transport=None, *, clock_ms=None, sleep=time.sleep, cancelled=None):
        self._transport = transport if transport is not None else _public_get
        self._clock = clock_ms if clock_ms is not None else lambda: int(time.time() * 1000)
        self._sleep = sleep
        self._cancelled = cancelled
        self._last_sent = {}
        self._cooldown_until_ms = 0
        self._local = threading.local()
        self.last_scan_report = {"status": "not_scanned"}
        self._signals = self._load_signals()
        fetch = self._signals.fetch_klines
        source_logger = self._signals.logger

        def observed_error(*args, **kwargs):
            context = getattr(self._local, "context", None)
            if context is not None:
                context["errors"].append("legacy_source_error")
            source_logger.error(*args, **kwargs)

        self._signals.logger = SimpleNamespace(
            error=observed_error, warning=source_logger.warning, info=source_logger.info)

        def observed_fetch(symbol, interval="1h", limit=200):
            df = fetch(symbol, interval, limit)
            context = getattr(self._local, "context", None)
            if context is not None:
                if df is None or len(df) < 60:
                    context["unavailable"].append(interval)
                if df is not None:
                    ts, _ = self._signals._KLINES_CACHE[(symbol, interval, limit)]
                    context["frames"][interval] = (ts, df)
            return df

        self._signals.fetch_klines = observed_fetch

    def _load_signals(self):
        path = Path(__file__).with_name("legacy_crypto13_snapshot") / "signals.py"
        source = path.read_bytes()
        if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
            raise ValueError("Legacy signal snapshot integrity failure")
        name = "_legacy_crypto13_" + uuid.uuid4().hex
        module = ModuleType(name)
        module.__package__ = name
        config = SimpleNamespace(TP_R_MULT=1.5, SL_R_MULT=1.0)
        request_shim = SimpleNamespace(get=self._request, exceptions=requests.exceptions)
        original_import = builtins.__import__

        def isolated_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 1 and name == "config":
                return config
            if level == 0 and name == "requests":
                return request_shim
            if level == 0 and name == "time":
                return SimpleNamespace(sleep=self._sleep)
            return original_import(name, globals, locals, fromlist, level)

        module.__dict__["__builtins__"] = dict(vars(builtins), __import__=isolated_import)
        # dataclasses needs the isolated module registered during class creation.
        sys.modules[name] = module
        try:
            exec(compile(source, str(path), "exec"), module.__dict__)
        finally:
            sys.modules.pop(name, None)
        clock = self._clock

        class ClockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromtimestamp(clock() / 1000, tz=tz)

        module.datetime = ClockDateTime
        return module

    def _request(self, url, *, params, timeout):
        prefix = "https://fapi.binance.com"
        path = url[len(prefix):] if url.startswith(prefix + "/") else ""
        if path not in _ROUTES or set(params) != _ROUTES[path]:
            raise ValueError("Disallowed public request")
        if params.get("symbol") not in SYMBOLS:
            raise ValueError("Disallowed symbol")
        if path.endswith("/klines") and (
            params["interval"] not in ("1h", "4h") or params["limit"] != 200
        ):
            raise ValueError("Disallowed klines parameters")
        try:
            status, body = self._transport(path, dict(params), timeout)
        except (requests.exceptions.Timeout, TimeoutError):
            raise requests.exceptions.Timeout("Public GET timeout") from None
        except Exception:
            raise requests.exceptions.RequestException("Public GET unavailable") from None

        def raise_for_status():
            if status != 200:
                raise requests.exceptions.HTTPError("Public GET status failure")

        def decode():
            if not isinstance(body, bytes) or len(body) > 2_000_000:
                raise ValueError("Invalid public response")
            return json.loads(body)

        return SimpleNamespace(status_code=status, raise_for_status=raise_for_status, json=decode)

    def _build(self, symbol):
        context = {"klines": {}, "unavailable": [], "frames": {}, "errors": []}
        self._local.context = context
        try:
            sig = self._signals.get_signal(symbol, "1h", **SIGNAL_OPTIONS)
        finally:
            self._local.context = None
        # All captured data has been observed before this decision completed.
        context["as_of_ms"] = self._clock()
        for interval, (ts, df) in context.pop("frames").items():
            context["klines"][interval] = dict(
                observed_at_ms=int(ts * 1000), columns=list(df.columns),
                rows=df.to_numpy(dtype=object).tolist())
        if sig is not None:
            context["source_levels"] = dict(entry_reference=sig.entry, tp=sig.tp, sl=sig.sl)
        return (None if sig is None else dict(asdict(sig), context=context)), context

    def cooldown_remaining_ms(self):
        return max(0, self._cooldown_until_ms - self._clock())

    def _check_cancelled(self):
        if self._cancelled is not None and self._cancelled():
            self.last_scan_report.update(status="cancelled", finished_at_ms=self._clock())
            raise ScanUnavailable("cancelled")

    def scan(self):
        """Scan ordered Auto46 in batches of five; stable score order, max three."""
        report = dict(status="scanning", started_at_ms=self._clock(), evaluated=0,
                      unavailable=[], errors=[])
        self.last_scan_report = report
        if self.cooldown_remaining_ms():
            report["status"] = "cooldown"
            return []
        candidates = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            for start in range(0, len(SYMBOLS), 5):
                self._check_cancelled()
                futures = [executor.submit(self._build, sym) for sym in SYMBOLS[start:start + 5]]
                wait(futures)  # Match gather: evaluate dedup only after the whole batch.
                self._check_cancelled()
                for symbol, future in zip(SYMBOLS[start:start + 5], futures):
                    try:
                        sig, context = future.result()
                    except Exception as exc:
                        report["errors"].append(dict(symbol=symbol, error_type=type(exc).__name__))
                        continue  # Original gather(return_exceptions=True).
                    if context["unavailable"]:
                        report["unavailable"].append(dict(symbol=symbol, intervals=context["unavailable"]))
                    elif not context.get("errors"):
                        report["evaluated"] += 1
                    for error in context.get("errors", []):
                        report["errors"].append(dict(symbol=symbol, error_type=error))
                    if sig is None or sig["score"] < 85:
                        continue
                    sent = self._last_sent.get(sig["symbol"])
                    if sent is not None and self._clock() - sent < 6 * 3600 * 1000:
                        continue
                    candidates.append(sig)
                self._sleep(0.7)
        candidates.sort(key=lambda sig: sig["score"], reverse=True)
        report.update(finished_at_ms=self._clock(), candidates=len(candidates),
                      selected=min(3, len(candidates)))
        if not report["evaluated"]:
            report["status"] = "unavailable"
            raise ScanUnavailable("No legacy symbols evaluated; see last_scan_report")
        report["status"] = "partial" if any(report[k] for k in (
            "unavailable", "errors")) else "ok"
        return candidates[:3]

    def mark_sent(self, symbol, now_ms):
        """Mark successful shadow admission only, never merely selected signals."""
        if symbol not in SYMBOLS or type(now_ms) is not int:
            raise ValueError("Invalid sent marker")
        self._last_sent[symbol] = now_ms

    def finish_scan(self, sent):
        """Start original 120s chat cooldown after at least one successful send."""
        if type(sent) is not int or not 0 <= sent <= 3:
            raise ValueError("Invalid sent count")
        if sent:
            self._cooldown_until_ms = self._clock() + 120_000

    def dump_state(self):
        return copy.deepcopy(dict(
            version=1, source_sha256=SOURCE_SHA256, rules_fingerprint=RULES_FINGERPRINT,
            last_sent=dict(self._last_sent),
            cooldown_until_ms=self._cooldown_until_ms,
            klines_cache=[dict(symbol=sym, interval=tf, limit=limit, timestamp=ts,
                               frame=dict(columns=list(df.columns),
                                          dtypes=[str(t) for t in df.dtypes],
                                          rows=df.to_numpy(dtype=object).tolist()))
                          for (sym, tf, limit), (ts, df) in self._signals._KLINES_CACHE.items()],
        ))

    def restore_state(self, state):
        """Restore only adapter state, atomically; no code or network is loaded."""
        if (state.get("version") != 1 or state.get("source_sha256") != SOURCE_SHA256
                or state.get("rules_fingerprint") != RULES_FINGERPRINT):
            raise ValueError("Incompatible legacy state")
        sent = dict(state["last_sent"])
        until = state["cooldown_until_ms"]
        if type(until) is not int or any(s not in SYMBOLS or type(t) is not int
                                        for s, t in sent.items()):
            raise ValueError("Invalid legacy state")
        cache = {}
        for item in state["klines_cache"]:
            key = (item["symbol"], item["interval"], item["limit"])
            if key[0] not in SYMBOLS or key[1] not in ("1h", "4h") or key[2] != 200:
                raise ValueError("Invalid cache key")
            frame = item["frame"]
            df = pd.DataFrame(frame["rows"], columns=frame["columns"])
            df = df.astype(dict(zip(frame["columns"], frame["dtypes"])))
            cache[key] = (float(item["timestamp"]), df)
        self._last_sent, self._cooldown_until_ms = sent, until
        self._signals._KLINES_CACHE = cache
