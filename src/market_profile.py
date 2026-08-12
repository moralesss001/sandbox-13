from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any


MARKET_PROFILE_VERSION = "v1"


@dataclass(frozen=True)
class MarketProfileMetadata:
    market_profile_v1: str
    market_profile_confidence: str
    rsi_zone: str
    profile_low_rsi: bool
    profile_very_low_rsi: bool
    profile_htf_short: bool
    profile_macd_false: bool
    profile_market_phase: str
    profile_session: str

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def rsi_zone(value: Any) -> str:
    try:
        rsi = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not isfinite(rsi):
        return "UNKNOWN"
    if rsi < 35.0:
        return "<35"
    if rsi < 40.0:
        return "35-40"
    if rsi <= 65.0:
        return "40-65"
    return ">65"


def classify_market_profile(
    *,
    setup_type: Any,
    rsi: Any,
    market_phase: Any,
    session: Any,
    trend_htf: Any,
    macd: Any,
    volume: Any,
) -> MarketProfileMetadata:
    setup = str(setup_type or "UNKNOWN").strip().lower()
    phase = str(market_phase or "UNKNOWN").strip().lower()
    normalized_session = str(session or "UNKNOWN").strip().upper()
    htf = str(trend_htf or "UNKNOWN").strip().upper()
    zone = rsi_zone(rsi)
    low_rsi = zone in {"<35", "35-40"}
    very_low_rsi = zone == "<35"
    htf_short = htf == "SHORT"
    macd_value = _boolean_value(macd)
    volume_value = _boolean_value(volume)
    macd_false = macd_value is False

    if setup == "rebound":
        profile = "REBOUND"
        confidence = _confidence(sum((low_rsi, htf_short, macd_false)), medium=1, high=2)
    elif setup == "continuation":
        profile = "CONTINUATION"
        continuation_factors = sum(
            (
                phase == "trend",
                htf == "LONG",
                macd_value is True,
                volume_value is True,
            )
        )
        confidence = _confidence(continuation_factors, medium=1, high=3)
    elif setup == "unknown" or (phase == "range" and setup != "rebound"):
        profile = "DEFENSIVE"
        defensive_factors = sum((setup == "unknown", phase == "range" and setup != "rebound"))
        confidence = "HIGH" if defensive_factors >= 2 else "MEDIUM"
    else:
        profile = "UNKNOWN"
        confidence = "LOW"

    return MarketProfileMetadata(
        market_profile_v1=profile,
        market_profile_confidence=confidence,
        rsi_zone=zone,
        profile_low_rsi=low_rsi,
        profile_very_low_rsi=very_low_rsi,
        profile_htf_short=htf_short,
        profile_macd_false=macd_false,
        profile_market_phase=phase.upper() if phase else "UNKNOWN",
        profile_session=normalized_session,
    )


def attach_market_profile(signal):
    metadata = classify_market_profile(
        setup_type=getattr(signal, "setup_type", None),
        rsi=getattr(signal, "rsi", None),
        market_phase=getattr(signal, "market_phase", None),
        session=getattr(signal, "session", None),
        trend_htf=getattr(signal, "trend_htf", None),
        macd=getattr(signal, "macd", None),
        volume=getattr(signal, "volume", None),
    )
    for key, value in metadata.as_dict().items():
        setattr(signal, key, value)
    signal.raw = dict(getattr(signal, "raw", {}) or {})
    signal.raw.update(metadata.as_dict())
    signal.raw["market_profile_version"] = MARKET_PROFILE_VERSION
    return signal


def _boolean_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and isfinite(float(value)) and float(value) in {0.0, 1.0}:
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    return None


def _confidence(count: int, *, medium: int, high: int) -> str:
    if count >= high:
        return "HIGH"
    if count >= medium:
        return "MEDIUM"
    return "LOW"
