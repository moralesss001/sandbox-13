import json

from copy import deepcopy

import pytest

from src.hypothesis_registry import (
    Hypothesis,
    HypothesisEvaluatorVersionError,
    HypothesisRegistry,
    VersionedEvaluatorRegistry,
)
from src.hypothesis_runner import HypothesisRunner
from src.live_paper_storage import LivePaperStorage
from src.live_research_engine import LiveResearchEngine
from src.market_profile import attach_market_profile
from src.paper_broker import PaperBroker
from src.portfolio import PaperPortfolio
from src.order_models import HypothesisDecision, SignalCandidate
from src.research_pack5 import (
    RESEARCH_PACK_005_CONDITION_VERSION,
    RESEARCH_PACK_005_ID,
)
from src.research_session_manager import ResearchSessionManager
from src.telegram_control import TelegramControlPanel


EXPECTED_IDS = {
    "baseline_rr15", "rsi_below_35", "rsi_35_40", "rsi_40_65", "rsi_above_65",
    "profile_rebound_all", "profile_rebound_low_rsi", "profile_rebound_very_low_rsi",
    "profile_rebound_htf_short", "profile_rebound_macd_false",
    "profile_rebound_low_rsi_htf_short", "profile_rebound_low_rsi_macd_false",
    "profile_rebound_low_rsi_htf_short_macd_false", "profile_rebound_us",
    "profile_rebound_asia", "profile_rebound_europe", "profile_continuation_all",
    "profile_continuation_trend", "profile_range_rebound", "profile_range_non_rebound",
    "profile_unknown_setup", "profile_rsi_above_65_unknown", "production_would_allow",
    "production_would_block", "block_rsi_below_35_only", "block_rsi_above_65_only",
    "block_bearish_pattern_only", "block_sl_width_only", "block_multiple_reasons",
}


def _signal(**updates):
    values = dict(
        symbol="BTCUSDT", timeframe="15m", direction="LONG", entry=100, sl=98, tp=103,
        rr_ratio=1.5, setup_type="rebound", rsi=34, market_phase="range", session="US",
        trend_htf="Short", macd=False, volume=True, production_would_allow=False,
        production_block_reasons=["rsi_below_35"],
    )
    values.update(updates)
    return attach_market_profile(SignalCandidate(**values))


def _decision(hypothesis_id, signal):
    return HypothesisRegistry(research_pack_id=RESEARCH_PACK_005_ID).get(hypothesis_id).decide(signal).decision


def test_research_005_registry_is_separate_and_complete():
    legacy = HypothesisRegistry()
    research = HypothesisRegistry(research_pack_id=RESEARCH_PACK_005_ID)
    assert {item.hypothesis_id for item in research.enabled()} == EXPECTED_IDS
    assert len(research.enabled()) == 29
    assert {item.hypothesis_id for item in legacy.enabled()} != EXPECTED_IDS


def test_interaction_hypotheses_select_exact_profiles():
    signal = _signal()
    for hypothesis_id in (
        "baseline_rr15", "rsi_below_35", "profile_rebound_all",
        "profile_rebound_very_low_rsi", "profile_rebound_htf_short",
        "profile_rebound_macd_false", "profile_rebound_low_rsi_htf_short_macd_false",
        "profile_rebound_us", "profile_range_rebound", "production_would_block",
        "block_rsi_below_35_only",
    ):
        assert _decision(hypothesis_id, signal) == "ALLOW"
    assert _decision("rsi_35_40", signal) == "BLOCK"
    assert _decision("production_would_allow", signal) == "BLOCK"


def test_production_block_attribution_distinguishes_only_and_multiple():
    sl_only = _signal(production_block_reasons=["sl_too_wide_15m"])
    multiple = _signal(production_block_reasons=["rsi_below_35", "sl_too_wide_15m"])
    bearish = _signal(production_block_reasons=["bearish_pattern_against_long"])
    assert _decision("block_sl_width_only", sl_only) == "ALLOW"
    assert _decision("block_multiple_reasons", sl_only) == "BLOCK"
    assert _decision("block_multiple_reasons", multiple) == "ALLOW"
    assert _decision("block_rsi_below_35_only", multiple) == "BLOCK"
    assert _decision("block_bearish_pattern_only", bearish) == "ALLOW"


def test_market_profile_metadata_flows_to_trade_and_append_storage(tmp_path):
    signal = _signal(
        rsi=39, production_would_allow=True, production_block_reasons=[],
        candidate_source="production_like_raw", candidate_source_version="v2",
    )
    portfolio = PaperPortfolio("baseline_rr15")
    broker = PaperBroker(portfolio, fee_rate=0, slippage_pct=0)
    broker.open_position(signal)
    trade = broker.close_position(portfolio.open_positions[0], reason="TP", exit_price=signal.tp)
    storage = LivePaperStorage(tmp_path)
    storage.append_closed_trades([trade])
    restored = storage.load_closed_trades()[0]
    assert restored.market_profile_v1 == "REBOUND"
    assert restored.market_profile_confidence == "HIGH"
    assert restored.rsi_zone == "35-40"
    assert restored.profile_low_rsi is True
    header = storage.closed_trades_path.read_text(encoding="utf-8").splitlines()[0]
    assert "market_profile_v1" in header
    assert "profile_macd_false" in header


def test_baseline_rr15_is_identical_between_legacy_and_research_005(tmp_path):
    original = _signal(
        rsi=50, setup_type="continuation", market_phase="trend", trend_htf="Long",
        macd=True, production_would_allow=True, production_block_reasons=[], result="win",
        candidate_source="production_like_raw", candidate_source_version="v2",
        raw={"close_time": 123},
    )
    legacy_signal = deepcopy(original)
    research_signal = deepcopy(original)
    legacy = HypothesisRunner(registry=HypothesisRegistry(), data_root=tmp_path / "legacy")
    research = HypothesisRunner(
        registry=HypothesisRegistry(research_pack_id=RESEARCH_PACK_005_ID),
        data_root=tmp_path / "research",
    )
    legacy_result = legacy.run_replay([legacy_signal])
    research_result = research.run_replay([research_signal])
    assert legacy_signal.candidate_id == research_signal.candidate_id
    assert legacy_result["metrics"]["baseline_rr15"] == research_result["metrics"]["baseline_rr15"]
    legacy_trade = legacy.portfolios["baseline_rr15"].closed_trades[0]
    research_trade = research.portfolios["baseline_rr15"].closed_trades[0]
    assert (legacy_trade.entry_price, legacy_trade.sl, legacy_trade.tp, legacy_trade.rr_ratio) == (
        research_trade.entry_price, research_trade.sl, research_trade.tp, research_trade.rr_ratio
    )


def test_live_engine_reads_registry_from_immutable_session_snapshot(tmp_path):
    manager = ResearchSessionManager(tmp_path)
    manager.ensure_initialized()
    registry = HypothesisRegistry(research_pack_id=RESEARCH_PACK_005_ID)
    session_id, paths = manager.create_session({
        "timeframe": "15m", "direction": "LONG_ONLY",
        "candidate_source": "production_like_raw", "candidate_source_version": "v2",
        "configured_symbols": ["BTCUSDT"], "research_pack_id": RESEARCH_PACK_005_ID,
        "hypotheses": [
            {
                "hypothesis_id": item.hypothesis_id,
                "name": item.name,
                "enabled": item.enabled,
                "priority": item.priority,
                "rules": list(item.rules),
                "condition_key": item.condition_key,
                "condition_version": item.condition_version,
            }
            for item in registry.enabled()
        ],
        "safety": {},
    })
    engine = LiveResearchEngine(
        {"api": {"mode": "paper"}, "safety": {}}, data_root=paths.root,
        status_store=manager.global_status_store, session_id=session_id, session_manager=manager,
    )
    assert {item.hypothesis_id for item in engine._session_registry().enabled()} == EXPECTED_IDS



def test_live_engine_uses_exact_hypothesis_subset_from_session_snapshot(tmp_path):
    manager = ResearchSessionManager(tmp_path)
    manager.ensure_initialized()
    session_id, paths = manager.create_session({
        "timeframe": "15m", "direction": "LONG_ONLY",
        "candidate_source": "production_like_raw", "candidate_source_version": "v2",
        "configured_symbols": ["BTCUSDT"], "research_pack_id": RESEARCH_PACK_005_ID,
        "hypotheses": [{
            "hypothesis_id": "baseline_rr15", "name": "Frozen baseline", "enabled": True,
            "priority": 99, "rules": ["frozen rule"],
            "condition_key": "baseline_rr15",
            "condition_version": RESEARCH_PACK_005_CONDITION_VERSION,
        }],
        "safety": {},
    })
    engine = LiveResearchEngine(
        {"api": {"mode": "paper"}, "safety": {}}, data_root=paths.root,
        status_store=manager.global_status_store, session_id=session_id, session_manager=manager,
    )
    registry = engine._session_registry()
    assert [item.hypothesis_id for item in registry.enabled()] == ["baseline_rr15"]
    assert registry.get("baseline_rr15").name == "Frozen baseline"
    assert registry.get("baseline_rr15").priority == 99


def test_snapshot_restore_uses_v1_after_current_pack_definition_changes(monkeypatch):
    snapshot = {
        "research_pack_id": RESEARCH_PACK_005_ID,
        "hypotheses": [{
            "hypothesis_id": "baseline_rr15",
            "name": "Frozen baseline",
            "enabled": True,
            "priority": 1,
            "rules": ["always allow"],
            "condition_key": "baseline_rr15",
            "condition_version": RESEARCH_PACK_005_CONDITION_VERSION,
        }],
    }
    changed = Hypothesis(
        "baseline_rr15", "Changed runtime", "changed", ["always block"], True, 1,
        lambda _signal: HypothesisDecision("baseline_rr15", "BLOCK", "runtime_changed"),
        condition_key="baseline_rr15", condition_version=2,
    )
    monkeypatch.setattr(
        "src.research_pack5.research_pack_005_hypotheses",
        lambda: [changed],
    )
    restored = HypothesisRegistry.from_snapshot(snapshot)
    assert restored.get("baseline_rr15").decide(_signal()).decision == "ALLOW"


@pytest.mark.parametrize(
    ("hypothesis_id", "condition_key", "condition_version"),
    [
        ("unknown_condition", "unknown_condition", 1),
        ("baseline_rr15", "baseline_rr15", 999),
    ],
)
def test_snapshot_restore_fails_closed_for_unknown_evaluator(
    hypothesis_id, condition_key, condition_version
):
    snapshot = {
        "research_pack_id": RESEARCH_PACK_005_ID,
        "hypotheses": [{
            "hypothesis_id": hypothesis_id,
            "condition_key": condition_key,
            "condition_version": condition_version,
        }],
    }
    with pytest.raises(HypothesisEvaluatorVersionError, match="missing hypothesis evaluator"):
        HypothesisRegistry.from_snapshot(snapshot)


def test_pre_version_research_005_snapshot_fails_closed():
    snapshot = {
        "research_pack_id": RESEARCH_PACK_005_ID,
        "hypotheses": [{"hypothesis_id": "baseline_rr15"}],
    }
    with pytest.raises(HypothesisEvaluatorVersionError, match="missing versioned"):
        HypothesisRegistry.from_snapshot(snapshot)


def test_snapshot_restore_fails_closed_for_mismatched_hypothesis_and_condition():
    snapshot = {
        "research_pack_id": RESEARCH_PACK_005_ID,
        "hypotheses": [{
            "hypothesis_id": "rsi_below_35",
            "condition_key": "baseline_rr15",
            "condition_version": RESEARCH_PACK_005_CONDITION_VERSION,
        }],
    }
    with pytest.raises(HypothesisEvaluatorVersionError, match="does not match"):
        HypothesisRegistry.from_snapshot(snapshot)


def test_versioned_registry_rejects_duplicate_key_and_version():
    registry = VersionedEvaluatorRegistry()
    evaluator = lambda _signal: HypothesisDecision("baseline_rr15", "ALLOW")
    registry.register("baseline_rr15", 1, evaluator)
    with pytest.raises(ValueError, match="Duplicate hypothesis evaluator registration"):
        registry.register("baseline_rr15", 1, evaluator)


def test_telegram_start_snapshots_research_005_pack(tmp_path):
    panel = TelegramControlPanel(data_root=tmp_path)
    response = panel.live_start("test")
    session_id = panel.status_store.read()["active_session_id"]
    paths = ResearchSessionManager(tmp_path).paths(session_id)
    snapshot = json.loads(paths.config_snapshot.read_text(encoding="utf-8"))
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    status = json.loads(paths.runtime_status.read_text(encoding="utf-8"))
    assert "session_id:" in response
    assert snapshot["research_pack_id"] == RESEARCH_PACK_005_ID
    assert {item["hypothesis_id"] for item in snapshot["hypotheses"]} == EXPECTED_IDS
    assert {item["condition_key"] for item in snapshot["hypotheses"]} == EXPECTED_IDS
    assert {item["condition_version"] for item in snapshot["hypotheses"]} == {
        RESEARCH_PACK_005_CONDITION_VERSION
    }
    assert manifest["research_pack_id"] == RESEARCH_PACK_005_ID
    assert status["research_pack_id"] == RESEARCH_PACK_005_ID
    assert status["raw_candidates_count"] == 0
    assert json.loads(paths.open_positions.read_text(encoding="utf-8")) == []

    panel.session_manager.finalize_session(
        session_id, stop_reason="STOP_LIVE_RESEARCH", unresolved_open_positions_count=0, latest_report_path=None
    )
    panel.live_start("test-second")
    second_id = panel.status_store.read()["active_session_id"]
    second_paths = panel.session_manager.paths(second_id)
    second_status = json.loads(second_paths.runtime_status.read_text(encoding="utf-8"))
    assert second_id != session_id
    assert second_status["research_pack_id"] == RESEARCH_PACK_005_ID
    assert second_status["raw_candidates_count"] == 0
    assert json.loads(second_paths.open_positions.read_text(encoding="utf-8")) == []
