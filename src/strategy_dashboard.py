"""Read-only product metrics derived from the durable shadow journal."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3


def number(value) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("non-finite dashboard value")
    return result


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _position_slippage(position: dict) -> Decimal:
    quantity = number(position["quantity"])
    long = position["side"] == "LONG"
    entry_quote = position.get("entry_quote") or {}
    entry_reference = entry_quote.get("askPrice" if long else "bidPrice")
    total = Decimal(0)
    if entry_reference is not None:
        reference = number(entry_reference)
        fill = number(position["entry_price"])
        total += quantity * ((fill - reference) if long else (reference - fill))
    exit_quote = position.get("exit_quote") or {}
    exit_reference = exit_quote.get("bidPrice" if long else "askPrice")
    if exit_reference is not None and position.get("exit_price") is not None:
        reference = number(exit_reference)
        fill = number(position["exit_price"])
        total += quantity * ((reference - fill) if long else (fill - reference))
    return max(total, Decimal(0))


def _runtime_seconds(row: dict, status: dict, now: datetime) -> int | None:
    started = status.get("started_at")
    if started is None and row.get("state") == "running":
        started = row.get("updated_at")
    if not started:
        return None
    try:
        start = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        report = json.loads(row["report"]) if row.get("report") else {}
        finished = report.get("finished_at")
        end = datetime.fromisoformat(finished.replace("Z", "+00:00")) if finished else now
        return max(0, int((end - start).total_seconds()))
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _read_state(ledger: Path) -> dict:
    db = sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        db.execute("PRAGMA query_only=ON")
        row = db.execute("SELECT body FROM state WHERE id=1").fetchone()
        if row is None:
            raise ValueError("shadow journal state missing")
        return json.loads(row[0])
    finally:
        db.close()


def journal_metrics(session_path, row, package, now=None) -> dict:
    """Build one version-scoped snapshot without mutating the journal."""
    path = Path(session_path)
    status_path = path / "runtime_status.json"
    status = json.loads(status_path.read_text()) if status_path.is_file() else {}
    base = {
        "strategy_id": package["strategy_id"],
        "version": package["version"],
        "adapter": package["adapter"],
        "status": row.get("state") if row else "not_started",
        "runtime_seconds": _runtime_seconds(row or {}, status, now or datetime.now(timezone.utc)),
        "deadline": package["deadline"],
        "result_scope": "live_shadow",
        "historical_results": "not_attached",
        "monthly_return_projection": None,
        "monthly_return_projection_reason": "not calculated; no full-calendar-month projection",
    }
    ledger = path / "shadow.sqlite3"
    if not ledger.is_file():
        diagnostic = package["adapter"] == "synthetic_noop_v1"
        return dict(base, metrics_available=diagnostic,
                    metrics_source="runtime_status" if diagnostic else "unavailable",
                    trades=int(status.get("fills", 0)) if diagnostic else None,
                    open_positions=int(status.get("positions", 0)) if diagnostic else None,
                    closed_trades=0 if diagnostic else None,
                    win_rate_pct=None, realized_pnl_usdt=None, unrealized_pnl_usdt=None,
                    net_pnl_usdt=None, period_return_pct=None, expectancy_usdt=None,
                    profit_factor=None, max_drawdown_usdt=None, fees_usdt=None,
                    slippage_usdt=None, funding_usdt=None,
                    data_gaps={"available": False, "reason": "no shadow journal"})

    state = _read_state(ledger)
    opened = list(state.get("positions", {}).values())
    closed = list(state.get("closed", {}).values())
    all_positions = opened + closed
    realized_values = [number(item["net_pnl"]) for item in closed]
    realized = sum(realized_values, Decimal(0))
    gross_profit = sum((value for value in realized_values if value > 0), Decimal(0))
    gross_loss = -sum((value for value in realized_values if value < 0), Decimal(0))
    profit_factor = gross_profit / gross_loss if gross_loss else None
    wins = sum(value > 0 for value in realized_values)

    curve = peak = Decimal(0)
    max_drawdown = Decimal(0)
    for item in sorted(closed, key=lambda value: (int(value.get("exit_ms", 0)), value.get("signal_id", ""))):
        curve += number(item["net_pnl"])
        peak = max(peak, curve)
        max_drawdown = max(max_drawdown, peak - curve)

    unrealized = Decimal(0)
    valuation_available = True
    for item in opened:
        quote = state.get("market", {}).get(item["symbol"], {}).get("quote")
        if quote is None:
            valuation_available = False
            break
        market_price = number(quote["bidPrice" if item["side"] == "LONG" else "askPrice"])
        direction = Decimal(1) if item["side"] == "LONG" else Decimal(-1)
        unrealized += (number(item["quantity"]) * (market_price - number(item["entry_price"])) * direction
                       - number(item.get("entry_fee", 0)) + number(item.get("funding", 0)))

    total = realized + unrealized if valuation_available else None
    initial = number(state["metadata"]["initial_balance"])
    fees = sum((number(item.get("entry_fee", 0)) + number(item.get("exit_fee", 0))
                for item in all_positions), Decimal(0))
    funding = sum((number(item.get("funding", 0)) for item in all_positions), Decimal(0))
    slippage = sum((_position_slippage(item) for item in all_positions), Decimal(0))
    health = state.get("health", {})
    unavailable = {symbol: value.get("reason") for symbol, value in health.items()
                   if not value.get("ready")}
    gap_positions = sum(bool(item.get("gap_exposure")) for item in all_positions)
    return dict(
        base,
        metrics_available=True,
        metrics_source="shadow.sqlite3/state",
        trades=len(all_positions),
        signals=len(state.get("signals", {})),
        open_positions=len(opened),
        closed_trades=len(closed),
        win_rate_pct=_text(Decimal(wins) * 100 / len(closed)) if closed else None,
        realized_pnl_usdt=_text(realized),
        unrealized_pnl_usdt=_text(unrealized) if valuation_available else None,
        unrealized_valuation="last recorded executable-side quote; incurred entry fee and funding included",
        net_pnl_usdt=_text(total),
        period_return_pct=_text(total * 100 / initial) if total is not None else None,
        expectancy_usdt=_text(realized / len(closed)) if closed else None,
        profit_factor=_text(profit_factor),
        profit_factor_reason="no realized losses" if gross_profit > 0 and not gross_loss else None,
        max_drawdown_usdt=_text(max_drawdown) if closed else None,
        max_drawdown_scope="closed-trade realized curve; intratrade equity drawdown not persisted",
        fees_usdt=_text(fees),
        slippage_usdt=_text(slippage),
        funding_usdt=_text(funding),
        data_gaps={"available": True, "unavailable_symbols": unavailable,
                   "gap_exposed_positions": gap_positions},
    )


def sandbox_counts(packages, sessions) -> dict:
    by_key = {(row["strategy_id"], row["version"]): row for row in sessions}
    counts = {"running": 0, "queued": 0, "finished": 0, "rejected": 0, "idle": 0}
    for package in packages:
        key = (package["package"]["strategy_id"], package["package"]["version"])
        row = by_key.get(key)
        if package["status"] == "rejected":
            counts["rejected"] += 1
        elif row and row["state"] == "running":
            counts["running"] += 1
        elif row and row["state"] == "queued":
            counts["queued"] += 1
        elif row and row["state"] in {"stopped", "completed", "failed", "expired"}:
            counts["finished"] += 1
        else:
            counts["idle"] += 1
    return counts
