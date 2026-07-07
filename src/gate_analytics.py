from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GateOutcomeSummary:
    gate_saved_from_loss: int = 0
    gate_missed_profit: int = 0
    gate_allowed_loss: int = 0
    gate_allowed_profit: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "gate_saved_from_loss": self.gate_saved_from_loss,
            "gate_missed_profit": self.gate_missed_profit,
            "gate_allowed_loss": self.gate_allowed_loss,
            "gate_allowed_profit": self.gate_allowed_profit,
        }


def classify_gate_outcome(trade: Any) -> str:
    production_would_allow = _safe_bool(_get(trade, "production_would_allow", True))
    r_value = _safe_float(_get(trade, "r", 0.0)) or 0.0
    if not production_would_allow and r_value < 0:
        return "gate_saved_from_loss"
    if not production_would_allow and r_value > 0:
        return "gate_missed_profit"
    if production_would_allow and r_value < 0:
        return "gate_allowed_loss"
    if production_would_allow and r_value > 0:
        return "gate_allowed_profit"
    return "neutral"


def summarize_gate_outcomes(trades: list[Any]) -> dict[str, int]:
    summary = {
        "gate_saved_from_loss": 0,
        "gate_missed_profit": 0,
        "gate_allowed_loss": 0,
        "gate_allowed_profit": 0,
    }
    for trade in trades:
        outcome = classify_gate_outcome(trade)
        if outcome in summary:
            summary[outcome] += 1
    return summary


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", "n"}:
            return False
        if normalized in {"true", "1", "yes", "y"}:
            return True
    return bool(value)
