from src.hypothesis_registry import HypothesisRegistry
from src.order_models import HypothesisDecisionType, SignalCandidate


def test_registry_contains_required_hypotheses():
    ids = {hypothesis.hypothesis_id for hypothesis in HypothesisRegistry().enabled()}

    assert "baseline_rr15" in ids
    assert "ban_rsi_below_35" in ids
    assert "ban_unclear_europe_rebound" in ids
    assert "ban_overlap" in ids
    assert len(ids) >= 15


def test_research_pack_2_rules_use_signal_and_raw_fields():
    registry = HypothesisRegistry(include_research_pack_2=True)
    signal = SignalCandidate(
        symbol="BTCUSDT", timeframe="15m", direction="LONG",
        entry=100, tp=115, sl=90, rsi=42, atr_pct=0.0065,
        session="EUROPE", setup_type="rebound", trend_htf="Short",
        raw={"hour_msk": 12, "market_mode": "IMPULSE_CONTINUATION:pullback_impulse", "score": 85},
    )

    assert registry.get("ban_unknown_setup").decide(signal).decision == HypothesisDecisionType.ALLOW.value
    assert registry.get("ban_rebound_without_htf_support").decide(signal).decision == HypothesisDecisionType.BLOCK.value
    assert registry.get("hour_10_14_msk").decide(signal).decision == HypothesisDecisionType.ALLOW.value
    assert registry.get("market_mode_pullback_impulse").decide(signal).decision == HypothesisDecisionType.ALLOW.value
    assert registry.get("score_80_90").decide(signal).decision == HypothesisDecisionType.ALLOW.value
    assert registry.get("allow_only_us").decide(signal).decision == HypothesisDecisionType.BLOCK.value


def test_research_pack_2_has_expected_total_without_duplicate_ids():
    ids = [
        hypothesis.hypothesis_id
        for hypothesis in HypothesisRegistry(include_research_pack_2=True).enabled()
    ]

    assert len(ids) == 69
    assert len(ids) == len(set(ids))


def test_research_pack_2_is_not_enabled_in_default_runtime_registry():
    ids = {hypothesis.hypothesis_id for hypothesis in HypothesisRegistry().enabled()}

    assert len(ids) == 15
    assert "allow_only_us" not in ids
