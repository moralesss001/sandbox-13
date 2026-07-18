from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .candidate_sources import PRODUCTION_LIKE_RAW_METADATA
from .order_models import SignalCandidate
from .production_parity_15m import evaluate_15m_long_candidate
from .session_classifier import normalize_session
from .shadow_gates import attach_shadow_gate_metadata


def production_like_raw_signal_from_klines(
    symbol: str,
    timeframe: str,
    klines: pd.DataFrame,
    htf_klines: pd.DataFrame | None = None,
) -> SignalCandidate | None:
    if timeframe != "15m" or htf_klines is None:
        return None

    evaluation = evaluate_15m_long_candidate(klines, htf_klines, symbol=symbol)
    parity = evaluation.candidate
    if parity is None:
        return None

    raw = dict(klines.iloc[-1].to_dict())
    raw.update(parity)
    raw.update(
        {
            "pre_candidate_boundary_passed": True,
            "pre_candidate_rejection_reason": None,
            "market_mode_gate_analytics_only": True,
            "rsi_gate_analytics_only": False,
        }
    )
    confidence_factors = dict(parity["confidence_factors"])
    confidence_factors.update(
        {
            "score": parity["score"],
            "score_analytics_only": True,
            "macd_ok": parity["macd"],
            "volume_ok": parity["volume"],
            "candle_strong": parity["candle_body"],
            "htf_aligned": parity["trend_htf"] == "Long",
        }
    )

    candidate = SignalCandidate(
        symbol=parity["symbol"],
        timeframe=parity["timeframe"],
        direction=parity["direction"],
        entry=parity["entry"],
        tp=parity["tp"],
        sl=parity["sl"],
        rr_ratio=parity["rr_ratio"],
        signal_id=parity["signal_id"],
        production_signal_id=parity["production_signal_id"],
        created_at=datetime.fromtimestamp(parity["source_candle_close_time_ms"] / 1000, tz=timezone.utc).isoformat(),
        rsi=parity["rsi"],
        atr=parity["atr"],
        atr_pct=parity["atr_pct"],
        sl_pct=parity["sl_pct"],
        risk_distance=parity["risk_distance"],
        reward_distance=parity["reward_distance"],
        actual_rr=parity["actual_rr"],
        score=parity["score"],
        pattern=parity["pattern"],
        supertrend_dir=parity["supertrend_dir"],
        macd=parity["macd"],
        volume=parity["volume"],
        market_mode_pre=parity["market_mode_pre"],
        market_mode_post=parity["market_mode_post"],
        market_phase=parity["market_phase"],
        session=normalize_session(parity["session_msk_raw"]),
        setup_type=parity["setup_type"],
        trend_htf=parity["trend_htf"],
        reason=parity["reason"],
        confidence_factors=confidence_factors,
        signal_source="production_like_raw_live",
        source="binance_public_rest",
        **PRODUCTION_LIKE_RAW_METADATA.as_candidate_kwargs(),
        raw=raw,
    )
    return attach_shadow_gate_metadata(candidate)
