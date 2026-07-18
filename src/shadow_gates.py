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


def rsi_gate(value: Any, minimum: float = 35.0, maximum: float = 65.0) -> ShadowGateResult:
    rsi = _safe_float(value)
    if rsi is None:
        return ShadowGateResult(
            gate_name="rsi_gate",
            gate_type="shadow",
            would_allow=True,
            would_block=False,
            reason="insufficient_data_for_shadow_gate",
            value=value,
            threshold={"minimum": minimum, "maximum": maximum},
            source="production_like_gate",
            severity="warning",
        )
    if rsi < minimum:
        return ShadowGateResult(
            gate_name="rsi_gate",
            gate_type="shadow",
            would_allow=False,
            would_block=True,
            reason="rsi_below_35",
            value=rsi,
            threshold={"minimum": minimum, "maximum": maximum},
        )
    if rsi > maximum:
        return ShadowGateResult(
            gate_name="rsi_gate",
            gate_type="shadow",
            would_allow=False,
            would_block=True,
            reason="rsi_above_65",
            value=rsi,
            threshold={"minimum": minimum, "maximum": maximum},
        )
    return ShadowGateResult(
        gate_name="rsi_gate",
        gate_type="shadow",
        would_allow=True,
        would_block=False,
        reason="rsi_ok",
        value=rsi,
        threshold={"minimum": minimum, "maximum": maximum},
    )


def pattern_against_long_gate(pattern: Any) -> ShadowGateResult:
    bearish_patterns = {
        "Bearish Engulfing",
        "Shooting Star",
        "Bearish Pinbar",
        "Evening Star",
        "Break+Retest Down",
    }
    value = None if pattern is None else str(pattern)
    blocked = value in bearish_patterns
    return ShadowGateResult(
        gate_name="pattern_against_long_gate",
        gate_type="shadow",
        would_allow=not blocked,
        would_block=blocked,
        reason="bearish_pattern_against_long" if blocked else "pattern_ok",
        value=value,
        threshold=sorted(bearish_patterns),
    )


def sl_width_gate(value: Any, minimum: float = 0.0075, maximum: float = 0.035) -> ShadowGateResult:
    sl_pct = _safe_float(value)
    threshold = {"minimum": minimum, "maximum": maximum}
    if sl_pct is None:
        return ShadowGateResult(
            gate_name="sl_width_gate",
            gate_type="shadow",
            would_allow=True,
            would_block=False,
            reason="insufficient_data_for_shadow_gate",
            value=value,
            threshold=threshold,
            source="production_like_gate",
            severity="warning",
        )
    if sl_pct < minimum:
        return ShadowGateResult(
            gate_name="sl_width_gate",
            gate_type="shadow",
            would_allow=False,
            would_block=True,
            reason="sl_too_tight_15m",
            value=sl_pct,
            threshold=threshold,
        )
    if sl_pct > maximum:
        return ShadowGateResult(
            gate_name="sl_width_gate",
            gate_type="shadow",
            would_allow=False,
            would_block=True,
            reason="sl_too_wide_15m",
            value=sl_pct,
            threshold=threshold,
        )
    return ShadowGateResult(
        gate_name="sl_width_gate",
        gate_type="shadow",
        would_allow=True,
        would_block=False,
        reason="sl_width_ok",
        value=sl_pct,
        threshold=threshold,
    )


def market_mode_gate(raw: dict[str, Any] | None) -> ShadowGateResult:
    raw = raw or {}
    value = raw.get("market_mode_15m") or raw.get("market_mode") or raw.get("market_phase")
    if value is None or str(value).strip() == "":
        reason = "insufficient_data_for_shadow_gate"
    else:
        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        reason = "market_mode_15m_no_trade" if "no_trade" in normalized or normalized in {"notrade", "none", "disabled"} else "market_mode_15m_ok"
    return ShadowGateResult(
        gate_name="market_mode_15m_gate",
        gate_type="analytics",
        would_allow=True,
        would_block=False,
        reason=reason,
        value=value,
        threshold="NO_TRADE",
        source="analytics_only",
        severity="analytics_only",
    )


def evaluate_shadow_gates(signal) -> list[dict[str, Any]]:
    raw = getattr(signal, "raw", {}) or {}
    return [
        rsi_gate(getattr(signal, "rsi", None)).as_dict(),
        pattern_against_long_gate(getattr(signal, "pattern", None) or raw.get("pattern")).as_dict(),
        sl_width_gate(getattr(signal, "sl_pct", None) if getattr(signal, "sl_pct", None) is not None else raw.get("sl_pct")).as_dict(),
        market_mode_gate(raw).as_dict(),
    ]


def production_decision_from_shadow_gates(shadow_gates: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    reasons = [
        str(gate.get("reason"))
        for gate in shadow_gates
        if gate.get("source") == "production_like_gate"
        and gate.get("severity") == "hard_in_production"
        and bool(gate.get("would_block"))
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
