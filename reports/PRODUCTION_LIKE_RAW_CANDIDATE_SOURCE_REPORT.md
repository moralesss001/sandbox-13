# Production-like Raw Candidate Source Report

## Summary

Status: READY

Task 5C-NEXT is implemented inside Crypto13Research Sandbox only. A new live candidate source, `production_like_raw`, was added as version `v1` for 15m LONG-only paper research. It creates raw LONG candidates from Binance public candle data before hard-gate rejection, then attaches shadow gate analytics without removing the candidate from the hypothesis/paper flow.

No production Crypto13 files were modified. No real Binance orders, private API keys, or testnet orders were added.

## Candidate Source Contract

| Field | Value |
|---|---|
| candidate_source | production_like_raw |
| candidate_source_version | v1 |
| is_placeholder | false |
| edge_conclusions_allowed | false |
| direction_support | LONG_ONLY |
| source_description | Production-like raw LONG candidate source before hard-gate rejection for sandbox research |

## Files Changed

- `src/candidate_sources.py`
- `src/production_like_raw_source.py`
- `src/live_research_engine.py`
- `src/main.py`
- `src/order_models.py`
- `src/paper_broker.py`
- `src/hypothesis_runner.py`
- `tests/test_candidate_sources.py`
- `tests/test_production_like_raw_source.py`
- `tests/test_live_paper_lifecycle.py`

## Implementation Notes

- `production_like_raw` supports only `15m` and `LONG`.
- It uses Binance public REST candle data through the existing market data provider.
- It does not emit SHORT candidates.
- It computes RSI, ATR percent, session, HTF trend proxy, setup type, market phase, market mode, impulse context, and analytics score.
- Score is stored as analytics only: `score_analytics_only=true`, `score_used_as_gate=false`.
- `LOW_SCORE` does not reject or remove a candidate.
- RSI and market mode gates are shadow analytics only. If they block, `production_would_allow=false` and block reasons are preserved, but the candidate still reaches `HypothesisRunner.process_signal()` when source/timeframe/direction are supported.
- Paper positions/trades and hypothesis events now preserve candidate source metadata.

## CLI Selection

Implemented:

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
```

Supported live source choices:

- `simplified_placeholder`
- `production_like_raw`

## Smoke Run

Command:

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
```

Result:

- Exit code: 0
- Signal source: `production_like_raw_live`
- Demo report: `data/demo_reports/demo_report_20260701_201018.md`

Status command:

```bash
./.venv/bin/python -m src.main status
```

Runtime status confirmed:

- `candidate_source=production_like_raw`
- `candidate_source_version=v1`
- `edge_conclusions_allowed=False`
- `direction_support=LONG_ONLY`
- `raw_candidates_count=1`
- `production_would_block_count=1`
- `shadow_blocked_but_tracked_count=1`
- `last_shadow_block_reasons=[market_mode_15m_no_trade]`
- `errors=0`

## Tests

Focused command:

```bash
./.venv/bin/python -m pytest -q tests/test_candidate_sources.py tests/test_production_like_raw_source.py tests/test_live_paper_lifecycle.py
```

Result: `20 passed, 1 warning`

Full command:

```bash
./.venv/bin/python -m pytest -q
```

Result: `93 passed, 1 warning`

Warning: urllib3 reports LibreSSL instead of OpenSSL. This is an environment warning and did not fail tests.

## Safety Checks

- Production folder was not touched.
- `production_like_raw_source.py` does not import production runtime code.
- Production reference zip was used only as read-only research context.
- No private Binance API key path was added.
- No real order path was added.
- No testnet order path was enabled.
- Runtime safety status remains paper/public-data only.

Existing `testnet_*` files remain safety stubs from earlier tasks and are disabled by default.

## Limitations

- This is production-like, not a production strategy import.
- HTF trend is a lightweight candle-derived proxy in this source version.
- Current shadow RSI gate uses the existing sandbox threshold from Task 5C-REAL.
- This source is for evidence collection only. `edge_conclusions_allowed=false` means no production decision should be made from this source alone.

## Final Status

READY for sandbox live paper research with explicit `--candidate-source production_like_raw`.

Do not deploy production decisions from this output. Continue using it only to collect paper evidence.
