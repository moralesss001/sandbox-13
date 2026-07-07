from src.order_models import SignalCandidate
from src.shadow_gates import attach_shadow_gate_metadata, market_mode_gate, rsi_gate


def _candidate(rsi=50, raw=None):
    return SignalCandidate(
        symbol="BTCUSDT",
        timeframe="15m",
        direction="LONG",
        entry=100,
        tp=110,
        sl=95,
        rsi=rsi,
        raw=raw or {},
    )


def test_shadow_gate_contract_exists():
    result = rsi_gate(32).as_dict()

    assert result["gate_name"] == "rsi_gate"
    assert result["gate_type"] == "shadow"
    assert result["would_allow"] is False
    assert result["would_block"] is True
    assert result["reason"] == "rsi_below_35"
    assert result["source"] == "production_like_gate"
    assert result["severity"] == "hard_in_production"


def test_rsi_gate_blocks_below_threshold_and_allows_equal_or_above():
    assert rsi_gate(34.9).would_block is True
    assert rsi_gate(35).would_allow is True
    assert rsi_gate(40).would_allow is True


def test_market_mode_gate_blocks_no_trade_when_data_exists():
    result = market_mode_gate({"market_mode_15m": "NO_TRADE"})

    assert result.would_block is True
    assert result.reason == "market_mode_15m_no_trade"


def test_missing_market_mode_does_not_crash_or_hard_block():
    result = market_mode_gate({})

    assert result.would_allow is True
    assert result.would_block is False
    assert result.reason == "insufficient_data_for_shadow_gate"


def test_candidate_carries_shadow_gate_metadata_and_production_decision():
    candidate = attach_shadow_gate_metadata(_candidate(rsi=32, raw={"market_mode_15m": "NO_TRADE"}))

    assert len(candidate.shadow_gates) == 2
    assert candidate.production_would_allow is False
    assert candidate.production_block_reasons == ["rsi_below_35", "market_mode_15m_no_trade"]
    assert candidate.raw["production_would_allow"] is False
    assert candidate.raw["shadow_gate_block_reasons"] == ["rsi_below_35", "market_mode_15m_no_trade"]
