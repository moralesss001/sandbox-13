from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ShadowGateResult:
    gate_name: str
    gate_type: str
    would_allow: bool
    would_block: bool
    reason: str
    value: Any = None
    threshold: Any = None
    source: str = "production_like_gate"
    severity: str = "hard_in_production"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rsi_gate(value: Any, threshold: float = 35.0) -> ShadowGateResult:
    rsi = _safe_float(value)
    if rsi is None:
        return ShadowGateResult(
            gate_name="rsi_gate",
            gate_type="shadow",
            would_allow=True,
            would_block=False,
            reason="insufficient_data_for_shadow_gate",
            value=value,
            threshold=threshold,
            source="production_like_gate",
            severity="warning",
        )
    if rsi < threshold:
        return ShadowGateResult(
            gate_name="rsi_gate",
            gate_type="shadow",
            would_allow=False,
            would_block=True,
            reason="rsi_below_35",
            value=rsi,
            threshold=threshold,
        )
    return ShadowGateResult(
        gate_name="rsi_gate",
        gate_type="shadow",
        would_allow=True,
        would_block=False,
        reason="rsi_ok",
        value=rsi,
        threshold=threshold,
    )


def market_mode_gate(raw: dict[str, Any] | None) -> ShadowGateResult:
    raw = raw or {}
    value = raw.get("market_mode_15m") or raw.get("market_mode") or raw.get("market_phase")
    if value is None or str(value).strip() == "":
        return ShadowGateResult(
            gate_name="market_mode_15m_gate",
            gate_type="shadow",
            would_allow=True,
            would_block=False,
            reason="insufficient_data_for_shadow_gate",
            value=value,
            threshold="NO_TRADE",
            source="production_like_gate",
            severity="warning",
        )
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    no_trade_values = {"no_trade", "notrade", "none", "disabled"}
    if normalized in no_trade_values or "no_trade" in normalized:
        return ShadowGateResult(
            gate_name="market_mode_15m_gate",
            gate_type="shadow",
            would_allow=False,
            would_block=True,
            reason="market_mode_15m_no_trade",
            value=value,
            threshold="NO_TRADE",
        )
    return ShadowGateResult(
        gate_name="market_mode_15m_gate",
        gate_type="shadow",
        would_allow=True,
        would_block=False,
        reason="market_mode_15m_ok",
        value=value,
        threshold="NO_TRADE",
    )


def evaluate_shadow_gates(signal) -> list[dict[str, Any]]:
    return [
        rsi_gate(getattr(signal, "rsi", None)).as_dict(),
        market_mode_gate(getattr(signal, "raw", {})).as_dict(),
    ]


def production_decision_from_shadow_gates(shadow_gates: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    reasons = [
        str(gate.get("reason"))
        for gate in shadow_gates
        if gate.get("source") == "production_like_gate" and bool(gate.get("would_block"))
    ]
    return len(reasons) == 0, reasons


def attach_shadow_gate_metadata(signal):
    shadow_gates = evaluate_shadow_gates(signal)
    production_would_allow, reasons = production_decision_from_shadow_gates(shadow_gates)
    signal.shadow_gates = shadow_gates
    signal.production_would_allow = production_would_allow
    signal.production_block_reasons = reasons
    signal.shadow_gate_block_reasons = reasons
    signal.raw = dict(signal.raw or {})
    signal.raw["shadow_gates"] = shadow_gates
    signal.raw["production_would_allow"] = production_would_allow
    signal.raw["production_block_reasons"] = reasons
    signal.raw["shadow_gate_block_reasons"] = reasons
    return signal
