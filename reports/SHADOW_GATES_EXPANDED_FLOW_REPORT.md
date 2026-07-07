# Shadow Gates Expanded Flow Report

## 1. Executive Summary

Status: `READY`

Task 5C-REAL implemented shadow gates and expanded candidate flow inside Crypto13Research. Production-style gates are now evaluated as analytics metadata, not hard filters in sandbox live paper flow.

Current flow:

```text
candidate created
  -> shadow gates evaluated
  -> production_would_allow / production_block_reasons attached
  -> candidate continues into hypotheses/paper flow
  -> virtual trade outcome records gate metadata
  -> reports can classify gate saved/missed/allowed outcomes
```

Current candidate source remains `simplified_placeholder`, so gate analytics are technical only until a production-like or real research candidate source is connected.

## 2. What Changed

- Added shadow gate contract.
- Implemented `rsi_gate` and `market_mode_15m_gate`.
- Added `shadow_gates`, `production_would_allow`, `production_block_reasons`, and `shadow_gate_block_reasons` to candidates and virtual trades.
- Updated live paper runtime counters for raw candidates and shadow gate outcomes.
- Ensured shadow gate blocks do not remove LONG candidates from sandbox hypothesis/paper flow.
- Enriched closed paper trades with production/shadow gate metadata.
- Added gate outcome analytics for saved loss / missed profit / allowed loss / allowed profit.
- Added shadow gate analytics to demo reports.

## 3. Files Changed

- `src/order_models.py`
- `src/signal_adapter.py`
- `src/live_research_engine.py`
- `src/runtime_status.py`
- `src/live_paper_storage.py`
- `src/paper_broker.py`
- `src/hypothesis_runner.py`
- `src/demo_report_builder.py`
- `tests/test_live_paper_lifecycle.py`
- `tests/test_paper_broker.py`

## 4. Files Created

- `src/shadow_gates.py`
- `src/gate_analytics.py`
- `tests/test_shadow_gates.py`
- `tests/test_gate_analytics.py`
- `reports/SHADOW_GATES_EXPANDED_FLOW_REPORT.md`
- `reports/SHADOW_GATES_EXPANDED_FLOW_REPORT.json`

## 5. Shadow Gate Contract

Each shadow gate result has:

- `gate_name`
- `gate_type: shadow`
- `would_allow`
- `would_block`
- `reason`
- `value`
- `threshold`
- `source`
- `severity`

Production-like gates use:

```text
source: production_like_gate
severity: hard_in_production
```

## 6. Implemented Shadow Gates

Implemented now:

- `rsi_gate`
- `market_mode_15m_gate`

Behavior:

- `rsi_gate` blocks when `rsi < 35` with reason `rsi_below_35`.
- `rsi_gate` allows when `rsi >= 35`.
- Missing RSI returns allow with reason `insufficient_data_for_shadow_gate`.
- `market_mode_15m_gate` blocks `NO_TRADE`-style values with reason `market_mode_15m_no_trade`.
- Missing market mode returns allow with reason `insufficient_data_for_shadow_gate`.

## 7. Expanded Candidate Flow

Shadow gates are attached in `src/signal_adapter.py` through `attach_shadow_gate_metadata()`.

Live flow now keeps candidates available for research even when production-like shadow gates would block them. For a LONG candidate with `production_would_allow=false`, the candidate still reaches `HypothesisRunner.process_signal()` and can open virtual paper trades if a hypothesis allows it.

## 8. production_would_allow Logic

Logic:

```text
if any production_like_gate has would_block=true:
    production_would_allow = false
else:
    production_would_allow = true
```

Reasons are stored in:

- `production_block_reasons`
- `shadow_gate_block_reasons`

Example:

```text
production_would_allow: false
production_block_reasons: ["rsi_below_35"]
```

## 9. Runtime Status Counters

Runtime status now includes:

- `shadow_gates_enabled`
- `raw_candidates_count`
- `production_would_allow_count`
- `production_would_block_count`
- `shadow_blocked_but_tracked_count`
- `shadow_gate_block_counts`
- `last_shadow_block_reasons`

`shadow_blocked_but_tracked_count` means a candidate would have been blocked by production-like gates, but sandbox kept it for research.

## 10. Closed Trade Enrichment

Virtual positions and closed trades now carry:

- `shadow_gates`
- `production_would_allow`
- `production_block_reasons`
- `shadow_gate_block_reasons`

For CSV storage, list fields are serialized as pipe-separated strings where appropriate, and nested `shadow_gates` are serialized as JSON text.

## 11. Gate Outcome Analytics

Added in `src/gate_analytics.py`.

Classification:

- `production_would_allow=false` and `R < 0` -> `gate_saved_from_loss`
- `production_would_allow=false` and `R > 0` -> `gate_missed_profit`
- `production_would_allow=true` and `R < 0` -> `gate_allowed_loss`
- `production_would_allow=true` and `R > 0` -> `gate_allowed_profit`

If there are no closed trades, analytics return zero counts.

## 12. Why Gates Are Shadow-only In Sandbox

Production may keep hard gates. Sandbox must not hard-block these candidates because blocked candidates lose observable TP/SL outcomes. Shadow gates let the system answer whether a production-like gate would have saved a loss or missed a profit.

## 13. Current Limitation: simplified_placeholder Source

The current source is still:

```text
candidate_source: simplified_placeholder
edge_conclusions_allowed: false
```

Because current source is simplified_placeholder, gate analytics are technical only until production-like or real entry source is connected.

## 14. What Remains For Production-like Candidate Source

Next source work should create a production-like raw candidate source inside sandbox, without reading or mutating production directly.

Required future properties:

- broader raw candidate stream;
- reliable context fields;
- source/version metadata;
- shadow gate compatibility;
- no real/testnet/private API.

## 15. What Remains For New Entry Models

Future new entry models should be separate adapters. RSI / Market Mode / HTF / session rules should remain shadow analytics until enough prospective paper data exists.

## 16. Risks

- Current gate analytics are technical only because source is simplified placeholder.
- Market mode gate often has insufficient data until a richer candidate source exists.
- Shadow-blocked SHORT candidates still cannot be tracked in current LONG-only MVP.
- CSV serialization stores nested gate details as JSON text, not normalized tables.

## 17. Safety Confirmations

- Sandbox only: `true`
- Production code changed: `false`
- Production read directly: `false`
- Private Binance API used: `false`
- Real orders added: `false`
- Testnet orders added: `false`
- Deploy changed: `false`
- Docker/systemd changed: `false`
- Telegram dashboard changed: `false`
- New entry strategy added: `false`
- Research Pack 2 live enabled: `false`
- TP/SL/RR/risk changed: `false`

## 18. Test Results

Command:

```bash
./.venv/bin/python -m pytest -q
```

Result:

```text
85 passed, 1 environment warning
```

The warning is the existing local urllib3/LibreSSL warning and is not a test failure.

