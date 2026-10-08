"""Bounded public USD-M REST observations, never historical quote reconstruction.

No credentials, retries, redirects, background polling or order endpoints.
Funding completeness means exhausting the REST range, not proving exchange
history has no gaps. REST bookTicker snapshots cannot recover quotes between polls.
"""

from __future__ import annotations

import http.client
import json
import math
import re
from decimal import Decimal
from urllib.parse import urlencode


class DataUnavailable(RuntimeError):
    """An observation is invalid, unavailable, or cannot be completed safely."""


_HOST = "fapi.binance.com"
_ROUTES = {
    "/fapi/v1/aggTrades": {"symbol", "fromId", "limit"},
    "/fapi/v1/ticker/bookTicker": {"symbol"},
    "/fapi/v1/fundingRate": {"symbol", "startTime", "endTime", "limit"},
    "/fapi/v1/time": set(),
}
_MAX_BYTES = 2_000_000
_MAX_INT = 2**63 - 1


def _integer(value, name, minimum=0, maximum=_MAX_INT):
    if type(value) is not int or not minimum <= value <= maximum:
        raise DataUnavailable(f"Invalid {name}")
    return value


def _symbol(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9_]{2,40}", value):
        raise DataUnavailable("Invalid symbol")
    return value


def _decimal(value, name, positive=True):
    if not isinstance(value, str) or len(value) > 128 or not re.fullmatch(
        r"-?[0-9]+(?:\.[0-9]+)?", value
    ):
        raise DataUnavailable(f"Invalid {name}")
    number = Decimal(value)
    if not number.is_finite() or (positive and number <= 0):
        raise DataUnavailable(f"Invalid {name}")
    return number


def _object(value):
    if not isinstance(value, dict) or "code" in value:
        raise DataUnavailable("Expected market-data object")
    return value


def _rows(value, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise DataUnavailable("Invalid market-data page")
    return [_object(row) for row in value]


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DataUnavailable("Duplicate JSON field")
        result[key] = value
    return result


def _bad_constant(value):
    raise DataUnavailable("Non-finite JSON constant")


def _public_get(path, params, timeout):
    if path not in _ROUTES or not set(params) <= _ROUTES[path]:
        raise DataUnavailable("Disallowed public route or parameters")
    # A fresh direct TLS connection avoids environment proxies and netrc auth.
    connection = http.client.HTTPSConnection(_HOST, timeout=timeout)
    try:
        target = path + ("?" + urlencode(params) if params else "")
        connection.request("GET", target, headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise DataUnavailable(f"Public HTTP status {response.status}")
        expected = response.length
        if expected is not None and expected > _MAX_BYTES:
            raise DataUnavailable("Oversized public response")
        body = response.read(_MAX_BYTES + 1)
        if expected is not None and len(body) != expected:
            raise DataUnavailable("Truncated public response")
        return response.status, body
    finally:
        connection.close()


class PublicShadowClient:
    """Validated raw Binance objects with no numeric coercion.

    transport is a test seam: callable(path, params, timeout) -> (status, bytes).
    The default transport only sends GET to the fixed public TLS host. timeout
    bounds socket operations (not DNS or total wall time); max_pages bounds each
    funding call. Callers own poll cadence, freshness policy and rate limiting.
    """

    def __init__(self, *, timeout=10.0, max_pages=20, transport=None):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise DataUnavailable("timeout must be in (0, 30] seconds")
        _integer(max_pages, "max_pages", 1, 100)
        self._timeout = float(timeout)
        self._max_pages = max_pages
        self._transport = transport if transport is not None else _public_get

    def _get(self, path, params):
        if path not in _ROUTES or not set(params) <= _ROUTES[path]:
            raise DataUnavailable("Disallowed public route or parameters")
        try:
            status, body = self._transport(path, params, self._timeout)
            if type(status) is not int or status != 200:
                raise DataUnavailable("Public request failed; redirects are forbidden")
            if not isinstance(body, bytes) or len(body) > _MAX_BYTES:
                raise DataUnavailable("Invalid or oversized response")
            return json.loads(body.decode("utf-8"), object_pairs_hook=_pairs,
                              parse_constant=_bad_constant)
        except DataUnavailable:
            raise
        except (OSError, http.client.HTTPException, ValueError, TypeError, RecursionError):
            raise DataUnavailable("Public response unavailable or malformed") from None

    def trades(self, symbol, from_id=None, limit=1000) -> list:
        params = {"symbol": _symbol(symbol), "limit": _integer(limit, "limit", 1, 1000)}
        if from_id is not None:
            params["fromId"] = _integer(from_id, "from_id")
        rows = _rows(self._get("/fapi/v1/aggTrades", params), limit)
        previous_id = None
        previous_time = 0
        for row in rows:
            ident = _integer(row.get("a"), "aggregate ID")
            first = _integer(row.get("f"), "first trade ID")
            last = _integer(row.get("l"), "last trade ID")
            timestamp = _integer(row.get("T"), "trade timestamp", 1)
            _decimal(row.get("p"), "price")
            quantity = _decimal(row.get("q"), "quantity")
            if "nq" in row:
                normal = _decimal(row["nq"], "normal quantity", positive=False)
                if not 0 <= normal <= quantity:
                    raise DataUnavailable("Invalid normal quantity")
            if type(row.get("m")) is not bool or first > last:
                raise DataUnavailable("Invalid trade fields")
            if "symbol" in row and row["symbol"] != symbol:
                raise DataUnavailable("Trade symbol mismatch")
            if (previous_id is not None and ident != previous_id + 1) or timestamp < previous_time:
                raise DataUnavailable("Unordered or incomplete aggregate trades")
            if previous_id is None and from_id is not None and ident != from_id:
                raise DataUnavailable("Requested aggregate ID unavailable")
            previous_id, previous_time = ident, timestamp
        return rows

    def quote(self, symbol) -> dict:
        """Current best bid/ask only; never a historical quote for a past trade."""
        row = _object(self._get("/fapi/v1/ticker/bookTicker", {"symbol": _symbol(symbol)}))
        if row.get("symbol") != symbol:
            raise DataUnavailable("Quote symbol mismatch")
        _integer(row.get("time"), "quote timestamp", 1)
        _integer(row.get("lastUpdateId"), "quote update ID")
        bid = _decimal(row.get("bidPrice"), "bid price")
        ask = _decimal(row.get("askPrice"), "ask price")
        _decimal(row.get("bidQty"), "bid quantity")
        _decimal(row.get("askQty"), "ask quantity")
        if bid > ask:
            raise DataUnavailable("Crossed quote")
        return row

    def funding(self, symbol, start_ms, end_ms) -> list:
        """Exhaust an inclusive range or raise; never return a partial prefix.

        markPrice must be the price in that exact funding record, never a latest
        mark or a nearest-time substitute. No fixed funding interval is assumed.
        """
        _symbol(symbol)
        cursor = _integer(start_ms, "start_ms")
        _integer(end_ms, "end_ms", cursor)
        result = []
        for _ in range(self._max_pages):
            page = _rows(self._get("/fapi/v1/fundingRate", {
                "symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": 1000,
            }), 1000)
            previous = cursor - 1
            for row in page:
                if row.get("symbol") != symbol:
                    raise DataUnavailable("Funding symbol mismatch")
                timestamp = _integer(row.get("fundingTime"), "funding timestamp", 1)
                if not previous < timestamp <= end_ms:
                    raise DataUnavailable("Unordered, duplicate or out-of-range funding")
                rate = _decimal(row.get("fundingRate"), "funding rate", positive=False)
                if rate != 0 or "markPrice" in row:
                    _decimal(row.get("markPrice"), "exact funding mark price")
                previous = timestamp
            result.extend(page)
            if len(page) < 1000 or previous == end_ms:
                return result
            cursor = previous + 1
        raise DataUnavailable("Funding page budget exhausted; range incomplete")

    def server_time(self) -> int:
        row = _object(self._get("/fapi/v1/time", {}))
        return _integer(row.get("serverTime"), "server timestamp", 1)
