"""Quote-based model fills. No exchange execution, strategy or legacy accounting."""
from __future__ import annotations

from decimal import Decimal


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("non-finite accounting value")
    return result


class ShadowExecution:
    def __init__(self, journal):
        self.journal = journal

    def record_signal(self, signal_id, symbol, side, quantity, decision_ms, context):
        if not signal_id or side not in {"LONG", "SHORT"} or number(quantity) <= 0:
            raise ValueError("invalid shadow signal")
        if not 0 <= context["as_of_ms"] <= decision_ms:
            raise ValueError("context must be known at decision time")
        meta = self.journal.read()["metadata"]
        if symbol not in meta["symbols"]:
            raise ValueError("symbol outside session universe")
        record = dict(signal_id=signal_id, symbol=symbol, side=side,
                      quantity=str(number(quantity)), decision_ms=decision_ms,
                      context=context, rules_hash=meta["rules_hash"],
                      rules_version=meta["rules_version"], code_revision=meta["code_revision"],
                      code_hash=meta["code_hash"])
        def save(state):
            state["signals"][signal_id] = record
        return self.journal.transact("signal:" + signal_id, "signal_context", record, save)

    @staticmethod
    def _quote(state, symbol, now_ms):
        health = state["health"].get(symbol, {})
        if not health.get("ready"):
            raise ValueError("entries/exits blocked: incomplete market data")
        quote = state["market"][symbol]["quote"]
        age = now_ms - int(quote["time"])
        if not 0 <= age <= state["metadata"]["max_quote_age_ms"]:
            raise ValueError("stale/future quote")
        return quote

    @staticmethod
    def _consume_quote(state, symbol, quote, buy, qty, now_ms):
        market = state["market"][symbol]
        latest_funding = max((e["fundingTime"] for e in state["funding"].values()
                              if e["symbol"] == symbol), default=0)
        if now_ms < max(market.get("funding_checked_ms", 0),
                        market.get("last_execution_ms", 0), latest_funding):
            raise ValueError("backdated execution")
        identity = [quote.get("lastUpdateId"), quote["time"]]
        used = market.get("quote_consumed", {"identity": identity, "buy": "0", "sell": "0"})
        if used["identity"] != identity:
            used = {"identity": identity, "buy": "0", "sell": "0"}
        side = "buy" if buy else "sell"
        consumed = number(used[side]) + qty
        if consumed > number(quote["askQty" if buy else "bidQty"]):
            raise ValueError("insufficient remaining displayed quote size")
        used[side] = str(consumed)
        market["quote_consumed"] = used
        market["last_execution_ms"] = now_ms

    def enter(self, signal_id, now_ms):
        def apply(state):
            signal = state["signals"][signal_id]
            if not all(state["health"].get(symbol, {}).get("ready")
                       for symbol in state["metadata"]["symbols"]):
                raise ValueError("entries blocked: incomplete session market data")
            if signal_id in state["positions"] or signal_id in state["closed"]:
                raise ValueError("signal already filled")
            quote = self._quote(state, signal["symbol"], now_ms)
            if int(quote["time"]) <= signal["decision_ms"]:
                raise ValueError("entry requires a post-signal quote")
            buy = signal["side"] == "LONG"
            qty = number(signal["quantity"])
            if qty > number(quote["askQty" if buy else "bidQty"]):
                raise ValueError("insufficient displayed top-of-book size")
            self._consume_quote(state, signal["symbol"], quote, buy, qty, now_ms)
            penalty = number(state["metadata"]["execution_penalty"])
            px = number(quote["askPrice" if buy else "bidPrice"]) * (1 + penalty if buy else 1 - penalty)
            notional = qty * px
            fee = notional * number(state["metadata"]["fee_rate"])
            reserved = sum((number(p["entry_notional"]) for p in state["positions"].values()), Decimal(0))
            if reserved + notional + fee > number(state["balance"]):
                raise ValueError("insufficient model collateral (leverage=1)")
            state["positions"][signal_id] = dict(
                signal_id=signal_id, symbol=signal["symbol"], side=signal["side"],
                quantity=str(qty), entry_price=str(px), entry_notional=str(notional),
                entry_ms=now_ms, entry_quote=quote, entry_fee=str(fee), funding="0",
                execution_model="sampled_top_of_book_v1", exchange_fill=False,
                gap_exposure=False)
            state["balance"] = str(number(state["balance"]) - fee)
        # Stable operation key makes a retry after a lost acknowledgement harmless.
        return self.journal.transact("entry:" + signal_id, "model_entry", {"signal_id": signal_id}, apply)

    def exit(self, signal_id, now_ms):
        def apply(state):
            position = state["positions"][signal_id]
            quote = self._quote(state, position["symbol"], now_ms)
            if int(quote["time"]) <= position["entry_ms"]:
                raise ValueError("exit requires a later quote")
            buy = position["side"] == "SHORT"
            qty = number(position["quantity"])
            if qty > number(quote["askQty" if buy else "bidQty"]):
                raise ValueError("insufficient displayed exit size")
            self._consume_quote(state, position["symbol"], quote, buy, qty, now_ms)
            penalty = number(state["metadata"]["execution_penalty"])
            px = number(quote["askPrice" if buy else "bidPrice"]) * (1 + penalty if buy else 1 - penalty)
            gross = qty * (px - number(position["entry_price"])) * (-1 if buy else 1)
            fee = qty * px * number(state["metadata"]["fee_rate"])
            position.update(exit_ms=now_ms, exit_price=str(px), exit_quote=quote,
                            exit_fee=str(fee), gross_pnl=str(gross),
                            net_pnl=str(gross - fee - number(position["entry_fee"]) + number(position["funding"])),
                            funding_final=False)
            state["balance"] = str(number(state["balance"]) + gross - fee)
            state["closed"][signal_id] = state["positions"].pop(signal_id)
        return self.journal.transact("exit:" + signal_id, "model_exit", {"signal_id": signal_id}, apply)

    def funding(self, event):
        symbol, stamp = event["symbol"], int(event["fundingTime"])
        rate = number(event["fundingRate"])
        mark = number(event["markPrice"])
        if stamp <= 0 or mark <= 0:
            raise ValueError("exact funding mark required")
        payload = dict(symbol=symbol, fundingTime=stamp, fundingRate=str(rate), markPrice=str(mark))
        def apply(state):
            for position in [*state["positions"].values(), *state["closed"].values()]:
                # Funding at an execution timestamp belongs to the previous quantity.
                if position["symbol"] != symbol or not position["entry_ms"] < stamp <= position.get("exit_ms", stamp):
                    continue
                amount = -number(position["quantity"]) * mark * rate * (1 if position["side"] == "LONG" else -1)
                position["funding"] = str(number(position["funding"]) + amount)
                state["balance"] = str(number(state["balance"]) + amount)
                if "net_pnl" in position:
                    position["net_pnl"] = str(number(position["net_pnl"]) + amount)
            state["funding"][symbol + ":" + str(stamp)] = payload
        return self.journal.transact("funding:" + symbol + ":" + str(stamp), "funding", payload, apply)

    def accounting(self):
        state = self.journal.read()
        unrealized = Decimal(0)
        for position in state["positions"].values():
            quote = state["market"].get(position["symbol"], {}).get("quote")
            if quote is None:
                return {"balance_usdt": state["balance"], "quote_equity_usdt": None}
            price = number(quote["bidPrice"] if position["side"] == "LONG" else quote["askPrice"])
            unrealized += number(position["quantity"]) * (price - number(position["entry_price"])) * (1 if position["side"] == "LONG" else -1)
        return {"balance_usdt": state["balance"],
                "quote_equity_usdt": str(number(state["balance"]) + unrealized),
                "equity_is_model_estimate": True, "funding_final": False}


class StandardShadowExecution(ShadowExecution):
    """Legacy-independent execution: fixed notional, observed book, delayed fills."""

    def record_signal(self, signal_id, symbol, side, quantity, decision_ms, context):
        if quantity is not None:
            raise ValueError("fixed-notional quantity is determined only at fill")
        if not signal_id or side not in {"LONG", "SHORT"} or not 0 <= context["as_of_ms"] <= decision_ms:
            raise ValueError("invalid standard shadow signal/context")
        meta = self.journal.read()["metadata"]
        if symbol not in meta["symbols"]:
            raise ValueError("symbol outside session universe")
        levels = context["source_levels"]
        entry, tp, sl = (number(levels[k]) for k in ("entry_reference", "tp", "sl"))
        if not (0 < sl < entry < tp if side == "LONG" else 0 < tp < entry < sl):
            raise ValueError("invalid source levels")
        record = dict(signal_id=signal_id, symbol=symbol, side=side, quantity=None,
                      fixed_notional_usdt=meta["fixed_notional_usdt"], decision_ms=decision_ms,
                      context=context, rules_hash=meta["rules_hash"], rules_version=meta["rules_version"],
                      code_revision=meta["code_revision"], code_hash=meta["code_hash"])
        def save(state):
            state["signals"][signal_id] = record
        return self.journal.transact("signal:" + signal_id, "signal_context", record, save)

    def enter(self, signal_id, now_ms):
        def apply(state):
            signal = state["signals"][signal_id]
            quote = self._quote(state, signal["symbol"], now_ms)
            earliest = signal["decision_ms"] + state["metadata"]["latency_ms"]
            if now_ms < earliest or int(quote["time"]) < earliest:
                raise ValueError("entry requires a quote after signal + latency")
            if signal_id in state["positions"] or signal_id in state["closed"]:
                raise ValueError("signal already filled")
            buy = signal["side"] == "LONG"
            penalty = number(state["metadata"]["execution_penalty"])
            px = number(quote["askPrice" if buy else "bidPrice"]) * (1 + penalty if buy else 1 - penalty)
            notional = number(state["metadata"]["fixed_notional_usdt"])
            qty = notional / px
            self._consume_quote(state, signal["symbol"], quote, buy, qty, now_ms)
            fee = notional * number(state["metadata"]["fee_rate"])
            reserved = sum((number(p["entry_notional"]) for p in state["positions"].values()), Decimal(0))
            if reserved + notional + fee > number(state["balance"]):
                raise ValueError("insufficient model collateral (leverage=1)")
            state["positions"][signal_id] = dict(
                signal_id=signal_id, symbol=signal["symbol"], side=signal["side"],
                quantity=str(qty), entry_price=str(px), entry_notional=str(notional),
                entry_ms=now_ms, entry_quote=quote, entry_fee=str(fee), funding="0",
                execution_model="STANDARD_SHADOW_EXECUTION", exchange_fill=False,
                gap_exposure=False, source_levels=signal["context"]["source_levels"])
            state["balance"] = str(number(state["balance"]) - fee)
        return self.journal.transact("entry:" + signal_id, "model_entry", {"signal_id": signal_id}, apply)

    def request_exit(self, signal_id, now_ms):
        """Persist the first observed executable-side touch, never backfill a quote."""
        state = self.journal.read()
        if signal_id in state.get("exit_intents", {}):
            return False
        position = state["positions"][signal_id]
        quote = self._quote(state, position["symbol"], now_ms)
        if int(quote["time"]) <= position["entry_ms"]:
            return False
        levels = position["source_levels"]
        long = position["side"] == "LONG"
        px = number(quote["bidPrice" if long else "askPrice"])
        tp, sl = number(levels["tp"]), number(levels["sl"])
        outcome = ("TP" if (px >= tp if long else px <= tp) else
                   "SL" if (px <= sl if long else px >= sl) else None)
        if outcome is None:
            return False
        intent = dict(signal_id=signal_id, decision_ms=now_ms,
                      trigger_quote=quote, trigger=outcome,
                      first_touch_verified=not position["gap_exposure"])
        def apply(current):
            current.setdefault("exit_intents", {})[signal_id] = intent
        return self.journal.transact("exit_intent:" + signal_id, "model_exit_intent", intent, apply)

    def exit(self, signal_id, now_ms):
        state = self.journal.read()
        if signal_id in state["closed"]:
            return False
        intent = state.get("exit_intents", {}).get(signal_id)
        if intent is None:
            raise ValueError("durable exit intent required")
        quote = self._quote(state, state["positions"][signal_id]["symbol"], now_ms)
        earliest = intent["decision_ms"] + state["metadata"]["latency_ms"]
        if now_ms < earliest or int(quote["time"]) < earliest:
            raise ValueError("exit requires a quote after intent + latency")
        return super().exit(signal_id, now_ms)
