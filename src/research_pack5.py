from __future__ import annotations

from .hypothesis_registry import Hypothesis, VersionedEvaluatorRegistry
from .order_models import HypothesisDecision, HypothesisDecisionType, SignalCandidate


RESEARCH_PACK_005_ID = "research_005"
RESEARCH_PACK_005_CONDITION_VERSION = 1


# Immutable v1 execution contract; add a new version instead of changing these predicates.
def _condition_definitions_v1() -> list[tuple[str, str, object]]:
    return [
        ("baseline_rr15", "All production-like raw candidates", lambda s: True),
        ("rsi_below_35", "RSI < 35", lambda s: _zone(s) == "<35"),
        ("rsi_35_40", "35 <= RSI < 40", lambda s: _zone(s) == "35-40"),
        ("rsi_40_65", "40 <= RSI <= 65", lambda s: _zone(s) == "40-65"),
        ("rsi_above_65", "RSI > 65", lambda s: _zone(s) == ">65"),
        ("profile_rebound_all", "Market Profile REBOUND", lambda s: _profile(s) == "REBOUND"),
        ("profile_rebound_low_rsi", "REBOUND and RSI < 40", lambda s: _profile(s) == "REBOUND" and s.profile_low_rsi),
        ("profile_rebound_very_low_rsi", "REBOUND and RSI < 35", lambda s: _profile(s) == "REBOUND" and s.profile_very_low_rsi),
        ("profile_rebound_htf_short", "REBOUND and HTF Short", lambda s: _profile(s) == "REBOUND" and s.profile_htf_short),
        ("profile_rebound_macd_false", "REBOUND and MACD false", lambda s: _profile(s) == "REBOUND" and s.profile_macd_false),
        ("profile_rebound_low_rsi_htf_short", "REBOUND, RSI < 40, HTF Short", lambda s: _profile(s) == "REBOUND" and s.profile_low_rsi and s.profile_htf_short),
        ("profile_rebound_low_rsi_macd_false", "REBOUND, RSI < 40, MACD false", lambda s: _profile(s) == "REBOUND" and s.profile_low_rsi and s.profile_macd_false),
        ("profile_rebound_low_rsi_htf_short_macd_false", "REBOUND, RSI < 40, HTF Short, MACD false", lambda s: _profile(s) == "REBOUND" and s.profile_low_rsi and s.profile_htf_short and s.profile_macd_false),
        ("profile_rebound_us", "REBOUND in US", lambda s: _profile(s) == "REBOUND" and _session(s) == "US"),
        ("profile_rebound_asia", "REBOUND in ASIA", lambda s: _profile(s) == "REBOUND" and _session(s) == "ASIA"),
        ("profile_rebound_europe", "REBOUND in EUROPE", lambda s: _profile(s) == "REBOUND" and _session(s) == "EUROPE"),
        ("profile_continuation_all", "Market Profile CONTINUATION", lambda s: _profile(s) == "CONTINUATION"),
        ("profile_continuation_trend", "CONTINUATION in trend phase", lambda s: _profile(s) == "CONTINUATION" and _phase(s) == "trend"),
        ("profile_range_rebound", "Range REBOUND", lambda s: _phase(s) == "range" and _profile(s) == "REBOUND"),
        ("profile_range_non_rebound", "Range non-REBOUND", lambda s: _phase(s) == "range" and _profile(s) != "REBOUND"),
        ("profile_unknown_setup", "Unknown setup", lambda s: _setup(s) == "unknown"),
        ("profile_rsi_above_65_unknown", "RSI > 65 and unknown setup", lambda s: _zone(s) == ">65" and _setup(s) == "unknown"),
        ("production_would_allow", "Production would allow", lambda s: bool(s.production_would_allow)),
        ("production_would_block", "Production would block", lambda s: not bool(s.production_would_allow)),
        ("block_rsi_below_35_only", "Only RSI below 35 blocks", lambda s: _only_reasons(s, {"rsi_below_35"})),
        ("block_rsi_above_65_only", "Only RSI above 65 blocks", lambda s: _only_reasons(s, {"rsi_above_65"})),
        ("block_bearish_pattern_only", "Only bearish pattern blocks", lambda s: _only_reasons(s, {"bearish_pattern_against_long"})),
        ("block_sl_width_only", "Only SL width blocks", _sl_width_only),
        ("block_multiple_reasons", "Multiple production block reasons", lambda s: len(_reasons(s)) > 1),
    ]


def research_pack_005_evaluator_registry() -> VersionedEvaluatorRegistry:
    registry = VersionedEvaluatorRegistry()
    for hypothesis_id, _rule, predicate in _condition_definitions_v1():
        registry.register(
            hypothesis_id,
            RESEARCH_PACK_005_CONDITION_VERSION,
            _allow_if(hypothesis_id, predicate),
        )
    return registry


def research_pack_005_hypotheses() -> list[Hypothesis]:
    registry = research_pack_005_evaluator_registry()
    return [
        Hypothesis(
            hypothesis_id=hypothesis_id,
            name=hypothesis_id.replace("_", " ").title(),
            description="Research #005 interaction hypothesis.",
            rules=[rule],
            enabled=True,
            priority=index + 1,
            evaluator=registry.resolve(hypothesis_id, RESEARCH_PACK_005_CONDITION_VERSION),
            condition_key=hypothesis_id,
            condition_version=RESEARCH_PACK_005_CONDITION_VERSION,
        )
        for index, (hypothesis_id, rule, _predicate) in enumerate(_condition_definitions_v1())
    ]


def _allow_if(hypothesis_id: str, predicate) -> object:
    def decide(signal: SignalCandidate) -> HypothesisDecision:
        allowed = bool(predicate(signal))
        return HypothesisDecision(
            hypothesis_id,
            HypothesisDecisionType.ALLOW.value if allowed else HypothesisDecisionType.BLOCK.value,
            None if allowed else f"outside_{hypothesis_id}",
        )

    return decide


def _profile(signal: SignalCandidate) -> str:
    return str(signal.market_profile_v1 or "UNKNOWN").upper()


def _zone(signal: SignalCandidate) -> str:
    return str(signal.rsi_zone or "UNKNOWN")


def _session(signal: SignalCandidate) -> str:
    return str(signal.session or "UNKNOWN").upper()


def _phase(signal: SignalCandidate) -> str:
    return str(signal.market_phase or "UNKNOWN").lower()


def _setup(signal: SignalCandidate) -> str:
    return str(signal.setup_type or "UNKNOWN").lower()


def _reasons(signal: SignalCandidate) -> set[str]:
    return {str(reason) for reason in signal.production_block_reasons if reason}


def _only_reasons(signal: SignalCandidate, expected: set[str]) -> bool:
    return _reasons(signal) == expected


def _sl_width_only(signal: SignalCandidate) -> bool:
    reasons = _reasons(signal)
    return len(reasons) == 1 and reasons.issubset({"sl_too_tight_15m", "sl_too_wide_15m"})
