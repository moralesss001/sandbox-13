from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .order_models import HypothesisDecision, HypothesisDecisionType, SignalCandidate


Rule = Callable[[SignalCandidate], HypothesisDecision]


@dataclass
class Hypothesis:
    hypothesis_id: str
    name: str
    description: str
    rules: list[str]
    enabled: bool = True
    priority: int = 100
    evaluator: Rule | None = None

    def decide(self, signal: SignalCandidate) -> HypothesisDecision:
        if self.evaluator is None:
            return HypothesisDecision(self.hypothesis_id, HypothesisDecisionType.ALLOW.value)
        return self.evaluator(signal)


def _allow(hypothesis_id: str) -> Rule:
    return lambda signal: HypothesisDecision(hypothesis_id, HypothesisDecisionType.ALLOW.value)


def _block_if(hypothesis_id: str, reason: str, predicate) -> Rule:
    def decide(signal: SignalCandidate) -> HypothesisDecision:
        if predicate(signal):
            return HypothesisDecision(hypothesis_id, HypothesisDecisionType.BLOCK.value, reason)
        return HypothesisDecision(hypothesis_id, HypothesisDecisionType.ALLOW.value)

    return decide


def _allow_if(hypothesis_id: str, reason: str, predicate) -> Rule:
    return _block_if(hypothesis_id, reason, lambda signal: not predicate(signal))


def _rsi(signal: SignalCandidate) -> float | None:
    return signal.rsi


def _session(signal: SignalCandidate) -> str:
    return str(signal.session or "UNKNOWN").upper()


def _phase(signal: SignalCandidate) -> str:
    return str(signal.market_phase or "UNKNOWN").lower()


def _setup(signal: SignalCandidate) -> str:
    return str(signal.setup_type or "UNKNOWN").lower()


def _trend_htf(signal: SignalCandidate) -> str:
    return str(signal.trend_htf or "UNKNOWN").upper()


def _raw_float(signal: SignalCandidate, field: str) -> float | None:
    try:
        value = signal.raw.get(field)
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _raw_text(signal: SignalCandidate, field: str) -> str:
    return str(signal.raw.get(field) or "").lower()


ATR_Q33 = 0.005941887712921817
ATR_Q66 = 0.007714203838014657


def _research_pack_2(start_priority: int = 16) -> list[Hypothesis]:
    specs: list[tuple[str, str, str, Rule]] = []

    def allow(hid: str, rule: str, predicate) -> None:
        specs.append((hid, hid.replace("_", " ").title(), rule, _allow_if(hid, f"outside_{hid}", predicate)))

    def block(hid: str, rule: str, predicate) -> None:
        specs.append((hid, hid.replace("_", " ").title(), rule, _block_if(hid, hid, predicate)))

    allow("ban_unknown_setup", "setup_type != unknown", lambda s: _setup(s) != "unknown")
    allow("allow_only_rebound", "setup_type == rebound", lambda s: _setup(s) == "rebound")
    allow("allow_only_unknown", "setup_type == unknown", lambda s: _setup(s) == "unknown")
    allow("ban_rebound", "setup_type != rebound", lambda s: _setup(s) != "rebound")
    block("ban_rebound_without_htf_support", "block rebound and HTF Short", lambda s: _setup(s) == "rebound" and _trend_htf(s) == "SHORT")
    allow("allow_rebound_only_if_htf_not_short", "rebound and HTF not Short", lambda s: _setup(s) == "rebound" and _trend_htf(s) != "SHORT")
    allow("allow_rebound_only_if_rsi_mid", "rebound and 40 <= RSI <= 65", lambda s: _setup(s) == "rebound" and _rsi(s) is not None and 40 <= _rsi(s) <= 65)
    allow("allow_continuation_only_rsi_40_65", "continuation and 40 <= RSI <= 65", lambda s: _setup(s) == "continuation" and _rsi(s) is not None and 40 <= _rsi(s) <= 65)
    allow("allow_long_only_if_htf_not_short", "trend_htf != Short", lambda s: _trend_htf(s) != "SHORT")
    allow("ban_htf_short_for_15m_long", "not 15m LONG with HTF Short", lambda s: not (s.timeframe.lower() == "15m" and s.direction.upper() == "LONG" and _trend_htf(s) == "SHORT"))
    allow("allow_countertrend_only_in_us_session", "HTF not Short or US", lambda s: _trend_htf(s) != "SHORT" or _session(s) == "US")
    allow("allow_countertrend_only_if_rsi_mid", "HTF not Short or 40 <= RSI <= 65", lambda s: _trend_htf(s) != "SHORT" or (_rsi(s) is not None and 40 <= _rsi(s) <= 65))
    allow("ban_europe", "session != EUROPE", lambda s: _session(s) != "EUROPE")
    allow("allow_only_us", "session == US", lambda s: _session(s) == "US")
    allow("allow_us_and_asia_only", "session in US, ASIA", lambda s: _session(s) in {"US", "ASIA"})
    block("ban_europe_rebound", "block EUROPE rebound", lambda s: _session(s) == "EUROPE" and _setup(s) == "rebound")
    block("ban_overlap_rebound", "block OVERLAP rebound", lambda s: _session(s) == "OVERLAP" and _setup(s) == "rebound")
    block("ban_europe_unknown", "block EUROPE unknown", lambda s: _session(s) == "EUROPE" and _setup(s) == "unknown")
    block("ban_overlap_unknown", "block OVERLAP unknown", lambda s: _session(s) == "OVERLAP" and _setup(s) == "unknown")
    allow("allow_us_continuation_only", "US continuation", lambda s: _session(s) == "US" and _setup(s) == "continuation")
    allow("allow_us_mid_rsi_only", "US and 40 <= RSI <= 65", lambda s: _session(s) == "US" and _rsi(s) is not None and 40 <= _rsi(s) <= 65)
    hour = lambda s: _raw_float(s, "hour_msk")
    allow("hour_10_14_msk", "10 <= hour_msk < 14", lambda s: hour(s) is not None and 10 <= hour(s) < 14)
    allow("hour_14_17_msk", "14 <= hour_msk < 17", lambda s: hour(s) is not None and 14 <= hour(s) < 17)
    allow("hour_17_20_msk", "17 <= hour_msk < 20", lambda s: hour(s) is not None and 17 <= hour(s) < 20)
    allow("hour_20_23_msk", "20 <= hour_msk < 23", lambda s: hour(s) is not None and 20 <= hour(s) < 23)
    allow("ban_hours_before_14_msk", "hour_msk >= 14", lambda s: hour(s) is not None and hour(s) >= 14)
    allow("allow_15_20_msk", "15 <= hour_msk < 20", lambda s: hour(s) is not None and 15 <= hour(s) < 20)
    allow("allow_17_20_msk", "17 <= hour_msk < 20", lambda s: hour(s) is not None and 17 <= hour(s) < 20)
    allow("allow_rsi_40_55", "40 <= RSI <= 55", lambda s: _rsi(s) is not None and 40 <= _rsi(s) <= 55)
    allow("allow_rsi_45_60", "45 <= RSI <= 60", lambda s: _rsi(s) is not None and 45 <= _rsi(s) <= 60)
    allow("allow_rsi_40_65", "40 <= RSI <= 65", lambda s: _rsi(s) is not None and 40 <= _rsi(s) <= 65)
    allow("ban_rsi_below_45", "RSI >= 45", lambda s: _rsi(s) is not None and _rsi(s) >= 45)
    allow("ban_rsi_above_60", "RSI <= 60", lambda s: _rsi(s) is not None and _rsi(s) <= 60)
    allow("ban_rsi_above_65", "RSI <= 65", lambda s: _rsi(s) is not None and _rsi(s) <= 65)
    atr = lambda s: s.atr_pct
    allow("atr_low_bucket", "ATR <= q33", lambda s: atr(s) is not None and atr(s) <= ATR_Q33)
    allow("atr_mid_bucket", "q33 < ATR <= q66", lambda s: atr(s) is not None and ATR_Q33 < atr(s) <= ATR_Q66)
    allow("atr_high_bucket", "ATR > q66", lambda s: atr(s) is not None and atr(s) > ATR_Q66)
    allow("ban_low_atr", "ATR > q33", lambda s: atr(s) is not None and atr(s) > ATR_Q33)
    allow("ban_high_atr", "ATR <= q66", lambda s: atr(s) is not None and atr(s) <= ATR_Q66)
    allow("allow_mid_atr_only", "q33 < ATR <= q66", lambda s: atr(s) is not None and ATR_Q33 < atr(s) <= ATR_Q66)
    block("low_atr_rebound_toxic", "block low ATR rebound", lambda s: atr(s) is not None and atr(s) <= ATR_Q33 and _setup(s) == "rebound")
    block("low_atr_unknown_toxic", "block low ATR unknown", lambda s: atr(s) is not None and atr(s) <= ATR_Q33 and _setup(s) == "unknown")
    block("high_atr_rebound_toxic", "block high ATR rebound", lambda s: atr(s) is not None and atr(s) > ATR_Q66 and _setup(s) == "rebound")
    mode = lambda s: _raw_text(s, "market_mode")
    allow("market_mode_pullback_impulse", "market_mode contains pullback_impulse", lambda s: "pullback_impulse" in mode(s))
    allow("market_mode_extreme_reversion", "market_mode contains extreme_reversion", lambda s: "extreme_reversion" in mode(s))
    block("ban_pullback_impulse_if_htf_short", "block pullback_impulse with HTF Short", lambda s: "pullback_impulse" in mode(s) and _trend_htf(s) == "SHORT")
    allow("allow_pullback_impulse_only_us", "pullback_impulse and US", lambda s: "pullback_impulse" in mode(s) and _session(s) == "US")
    allow("ban_extreme_reversion", "market_mode excludes extreme_reversion", lambda s: "extreme_reversion" not in mode(s))
    score = lambda s: _raw_float(s, "score")
    allow("score_70_80", "70 <= score < 80", lambda s: score(s) is not None and 70 <= score(s) < 80)
    allow("score_80_90", "80 <= score < 90", lambda s: score(s) is not None and 80 <= score(s) < 90)
    allow("score_90_plus", "score >= 90", lambda s: score(s) is not None and score(s) >= 90)
    allow("allow_score_80_plus", "score >= 80", lambda s: score(s) is not None and score(s) >= 80)
    allow("allow_score_90_plus", "score >= 90", lambda s: score(s) is not None and score(s) >= 90)
    allow("ban_score_below_80", "score >= 80", lambda s: score(s) is not None and score(s) >= 80)
    return [Hypothesis(hid, name, "Research Pack 2 old-sample rule.", [rule], True, start_priority + index, evaluator) for index, (hid, name, rule, evaluator) in enumerate(specs)]


def default_hypotheses(include_research_pack_2: bool = False) -> list[Hypothesis]:
    specs = [
        Hypothesis("baseline_rr15", "Baseline RR 1.5", "No extra filters.", ["allow_all"], True, 1),
        Hypothesis(
            "ban_rsi_below_35",
            "Ban RSI < 35",
            "Blocks signals with RSI below 35.",
            ["rsi >= 35"],
            True,
            2,
            _block_if("ban_rsi_below_35", "rsi_below_35", lambda s: _rsi(s) is not None and _rsi(s) < 35),
        ),
        Hypothesis(
            "ban_rsi_below_38",
            "Ban RSI < 38",
            "Blocks signals with RSI below 38.",
            ["rsi >= 38"],
            True,
            3,
            _block_if("ban_rsi_below_38", "rsi_below_38", lambda s: _rsi(s) is not None and _rsi(s) < 38),
        ),
        Hypothesis(
            "ban_rsi_below_40",
            "Ban RSI < 40",
            "Blocks signals with RSI below 40.",
            ["rsi >= 40"],
            True,
            4,
            _block_if("ban_rsi_below_40", "rsi_below_40", lambda s: _rsi(s) is not None and _rsi(s) < 40),
        ),
        Hypothesis(
            "ban_unclear_europe_rebound",
            "Ban unclear + Europe + rebound",
            "Blocks the main toxic cluster from latest research.",
            ["market_phase != unclear OR session != europe OR setup != rebound"],
            True,
            5,
            _block_if(
                "ban_unclear_europe_rebound",
                "unclear_europe_rebound",
                lambda s: _phase(s) == "unclear" and "EUROPE" in _session(s) and _setup(s) == "rebound",
            ),
        ),
        Hypothesis(
            "ban_overlap",
            "Ban overlap session",
            "Blocks OVERLAP/EU_US session candidates.",
            ["session != overlap"],
            True,
            6,
            _block_if("ban_overlap", "overlap_session", lambda s: "OVERLAP" in _session(s) or "EU_US" in _session(s)),
        ),
        Hypothesis(
            "ban_unclear_low_rsi",
            "Ban unclear + low RSI",
            "Blocks unclear phase when RSI is below 40.",
            ["market_phase != unclear OR rsi >= 40"],
            True,
            7,
            _block_if(
                "ban_unclear_low_rsi",
                "unclear_low_rsi",
                lambda s: _phase(s) == "unclear" and _rsi(s) is not None and _rsi(s) < 40,
            ),
        ),
        Hypothesis(
            "ban_low_rsi_europe",
            "Ban low RSI Europe",
            "Blocks Europe signals with RSI below 40.",
            ["session != europe OR rsi >= 40"],
            True,
            8,
            _block_if(
                "ban_low_rsi_europe",
                "low_rsi_europe",
                lambda s: "EUROPE" in _session(s) and _rsi(s) is not None and _rsi(s) < 40,
            ),
        ),
        Hypothesis(
            "ban_rebound_europe",
            "Ban rebound Europe",
            "Blocks rebound setup in Europe.",
            ["session != europe OR setup != rebound"],
            True,
            9,
            _block_if(
                "ban_rebound_europe",
                "rebound_europe",
                lambda s: "EUROPE" in _session(s) and _setup(s) == "rebound",
            ),
        ),
        Hypothesis(
            "ban_unclear_europe",
            "Ban unclear Europe",
            "Blocks unclear phase in Europe.",
            ["session != europe OR market_phase != unclear"],
            True,
            10,
            _block_if(
                "ban_unclear_europe",
                "unclear_europe",
                lambda s: "EUROPE" in _session(s) and _phase(s) == "unclear",
            ),
        ),
        Hypothesis(
            "allow_only_mid_rsi",
            "Allow only mid RSI",
            "Allows only RSI from 40 to 65.",
            ["40 <= rsi <= 65"],
            True,
            11,
            _block_if(
                "allow_only_mid_rsi",
                "rsi_outside_mid_range",
                lambda s: _rsi(s) is None or _rsi(s) < 40 or _rsi(s) > 65,
            ),
        ),
        Hypothesis(
            "allow_only_continuation",
            "Allow only continuation",
            "Allows only continuation setup.",
            ["setup_type == continuation"],
            True,
            12,
            _block_if("allow_only_continuation", "not_continuation", lambda s: _setup(s) != "continuation"),
        ),
        Hypothesis(
            "allow_us_unknown",
            "Allow US unknown",
            "Allows only US session with unknown/unclear phase.",
            ["session == US AND market_phase in unknown/unclear"],
            True,
            13,
            _block_if(
                "allow_us_unknown",
                "not_us_unknown",
                lambda s: "US" not in _session(s) or _phase(s) not in {"unknown", "unclear"},
            ),
        ),
        Hypothesis(
            "ban_unclear_overlap",
            "Ban unclear overlap",
            "Blocks unclear phase during overlap.",
            ["market_phase != unclear OR session != overlap"],
            True,
            14,
            _block_if(
                "ban_unclear_overlap",
                "unclear_overlap",
                lambda s: _phase(s) == "unclear" and ("OVERLAP" in _session(s) or "EU_US" in _session(s)),
            ),
        ),
        Hypothesis(
            "ban_europe_low_rsi",
            "Ban Europe low RSI",
            "Alias of low-RSI Europe filter for comparison.",
            ["session != europe OR rsi >= 40"],
            True,
            15,
            _block_if(
                "ban_europe_low_rsi",
                "europe_low_rsi",
                lambda s: "EUROPE" in _session(s) and _rsi(s) is not None and _rsi(s) < 40,
            ),
        ),
    ]
    if include_research_pack_2:
        specs.extend(_research_pack_2())
    for hypothesis in specs:
        if hypothesis.evaluator is None:
            hypothesis.evaluator = _allow(hypothesis.hypothesis_id)
    return specs


class HypothesisRegistry:
    def __init__(
        self,
        hypotheses: list[Hypothesis] | None = None,
        include_research_pack_2: bool = False,
    ):
        self._hypotheses = hypotheses or default_hypotheses(include_research_pack_2)

    def enabled(self) -> list[Hypothesis]:
        return sorted([h for h in self._hypotheses if h.enabled], key=lambda h: h.priority)

    def all(self) -> list[Hypothesis]:
        return list(self._hypotheses)

    def get(self, hypothesis_id: str) -> Hypothesis:
        for hypothesis in self._hypotheses:
            if hypothesis.hypothesis_id == hypothesis_id:
                return hypothesis
        raise KeyError(hypothesis_id)
