# Live Paper Readiness Audit

**Mode used:** HIGH / SURGICAL PATCH ONLY / AUDIT-ONLY  
**Workspace:** `/Users/maksimmatveev/Desktop/Crypto13 Research Sandbox/crypto13_research`  
**Production touched:** `false`  
**Overall readiness:** `PARTIAL`

## Executive Summary

Crypto13Research has a strong research/replay base and partial live paper foundation. Public Binance candles, simplified live signal generation, hypothesis evaluation, paper broker primitives, runtime status, Telegram control buttons, deployment examples, and safety guards already exist.

The system is **not ready for unattended Live Paper MVP** yet because the live loop does not fully manage the paper trade lifecycle: virtual positions can be opened, but TP/SL tracking is not wired into each closed-candle iteration and open virtual positions are not durably persisted across restarts.

The next patch should be small: complete the live paper lifecycle with public 15m candles, LONG-only candidates or a clearly marked placeholder adapter, virtual open/close handling, durable open/closed storage, and a basic leaderboard/status report. No production integration yet.

## Repository State

- branch: `main`
- latest commit: `50d1550 (HEAD -> main) chore: initialize local sandbox baseline`
- remotes: `none`
- `.env`: `missing`
- `.env.example`: `exists`
- AGENTS.md: `exists`
- local skill: `exists`
- production path touched in this audit: `false`

### Git Status Short

```text
?? candidate
?? data/
?? deployment/
?? handoffs/
?? hypothesis
?? leaderboard
?? metrics
?? paper
?? reports/
?? signal
```

### Ignored / Untracked Notes

```text
?? candidate
?? data/
?? deployment/
?? handoffs/
?? hypothesis
?? leaderboard
?? metrics
?? paper
?? reports/
?? signal
!! .DS_Store
!! .pytest_cache/
!! .venv/
!! data/.DS_Store
!! data/candles/
!! data/demo_reports/
!! data/hypothesis_events/
!! data/journals/
!! data/live_market/
!! data/paper_portfolios/
!! data/paper_trades/
!! data/runtime/
!! data/testnet_logs/
```

Important: `data/`, `reports/`, `deployment/`, and several marker directories are currently untracked from git's perspective. `data/candles/`, generated CSVs, `.venv`, `.env`, and runtime files are ignored. Before GitHub publication, decide what reports/docs should be committed and keep journals/candles/local runtime data out of the repo.

## Architecture Inventory

| zone | exists | responsibility | important files | limitations |
| --- | --- | --- | --- | --- |
| README.md | yes | Human-facing usage, safety rules, CLI commands, Telegram/deploy notes. | README.md | May lag behind implementation details; must not be treated as runtime config. |
| PROJECT_CONTEXT.md | yes | Project memory and strategic constraints. | PROJECT_CONTEXT.md | Documentation only. |
| RESEARCH_ROADMAP.md | yes | Roadmap for paper/demo/testnet direction. | RESEARCH_ROADMAP.md | Roadmap, not proof of implementation. |
| AGENTS.md | yes | Agent boundaries, Desktop sandbox as writable root, production read-only. | AGENTS.md | Requires humans/agents to follow it; not runtime enforcement. |
| .skills/ | yes | Local Crypto13 change guard skill. | .skills/crypto13-change-guardian/SKILL.md | Process guard, not code guard. |
| config/ | yes | Research config, hypotheses config, adaptive rules placeholder. | config/research_config.yaml, config/hypotheses.yaml, config/adaptive_rules.yaml | Research Pack 2 config has 69 IDs, but default runtime registry intentionally uses 15 unless include flag is passed. |
| configs/ | no | Target architecture folder from AGENTS spec. |  | Missing; current project uses singular config/. |
| docs/ | yes | Chat/subagent protocol docs. | docs/CHAT_PROTOCOL.md, docs/SUBAGENT_WORKFLOW.md | Coordination docs only. |
| src/ | yes | Core Python implementation for replay, hypotheses, paper broker, live research, Telegram, safety. | __init__.py, backtest_engine.py, binance_data.py, cluster_validator.py, combination_analyzer.py, command_queue.py, config.py, demo_report_builder.py, execution_safety.py, hypothesis_registry.py, hypothesis_runner.py, journal_loader.py, live_research_engine.py, live_shadow.py, main.py, market_context.py, metrics.py, models.py, order_models.py, paper_broker.py, portfolio.py, replay_engine.py, report_builder.py, research_pack2.py, risk_mode.py, runtime_status.py, session_classifier.py, signal_adapter.py, strategy_mode.py, telegram_bot.py, telegram_buttons.py, telegram_config.py, telegram_control.py, telegram_handlers.py, testnet_broker.py, trend_context_analyzer.py | Live paper lifecycle is partial; signal builder is simplified. |
| bot/ | no | Target future bot app folder. |  | Missing; current Telegram bot lives in src/. |
| tests/ | yes | Pytest coverage for loaders, hypotheses, paper broker, runtime, Telegram, safety. | test_cluster_validator.py, test_combination_analyzer.py, test_command_queue.py, test_deployment_docs.py, test_execution_safety.py, test_hypothesis_registry.py, test_hypothesis_runner.py, test_journal_loader.py, test_live_research_runtime.py, test_metrics.py, test_paper_broker.py, test_portfolio_metrics.py, test_risk_mode.py, test_runtime_status.py, test_session_classifier.py, test_signal_adapter.py, test_strategy_mode.py, test_telegram_config.py, test_telegram_handlers.py, test_trend_context_analyzer.py | System python unittest fails without deps; project tests are pytest-based. |
| reports/ | yes | Top-level research and audit reports. | CANDLE_COVERAGE_REPORT.md, HYPOTHESIS_COVERAGE_AUDIT.json, HYPOTHESIS_COVERAGE_AUDIT.md, HYPOTHESIS_OLD_SAMPLE_REPORT.json, HYPOTHESIS_OLD_SAMPLE_REPORT.md, HYPOTHESIS_OLD_SAMPLE_REPORT_SESSION_NORMALIZED.json, HYPOTHESIS_OLD_SAMPLE_REPORT_SESSION_NORMALIZED.md, OLD_SAMPLE_RESEARCH_SUMMARY.md, OLD_SAMPLE_SESSION_NORMALIZATION_SUMMARY.md, RESEARCH_PACK_2_REPORT.json, RESEARCH_PACK_2_REPORT.md, RR_REPLAY_OLD_SAMPLE_REPORT.json, RR_REPLAY_OLD_SAMPLE_REPORT.md | Untracked generated artifacts; decide what to commit before GitHub. |
| data/ | yes | Local journals, candles, runtime status, paper outputs, demo reports. | data/journals/, data/candles/, data/runtime/, data/paper_trades/, data/paper_portfolios/ | Mostly ignored/untracked and should not be blindly committed. |
| deployment/ | yes | Docker/systemd deployment examples for paper-only services. | deployment/README_DEPLOY.md, deployment/docker/Dockerfile, deployment/systemd/*.service.example | Untracked; not validated against Railway in this audit. |

## Completed Task Memory

| task | status | modules likely involved | reports | known limitations |
| --- | --- | --- | --- | --- |
| Task 1 — Telegram Inbox + Production CSV Compatibility | DONE/PARTIAL | src/telegram_*, src/journal_loader.py, src/signal_adapter.py | handoffs/documents_migration_archive/TASK_1_TELEGRAM_INBOX_CSV_COMPATIBILITY_REPORT.md | Compatibility exists for old journal columns; rejected_signals/technical_skips full join remains future work. |
| Task 2 — RR Replay + TP/SL Path Simulator + MAE/MFE | DONE for old sample | reports/RR_REPLAY_OLD_SAMPLE_REPORT.*, src/research_pack2.py old sample replay helper | reports/RR_REPLAY_OLD_SAMPLE_REPORT.md, reports/RR_REPLAY_OLD_SAMPLE_REPORT.json | RR replay is report artifact/code path, not a polished CLI subcommand in src.main. |
| Task 3 — Hypotheses Registry + Hypothesis Runner | DONE/PARTIAL | src/hypothesis_registry.py, src/hypothesis_runner.py, src/paper_broker.py, src/portfolio.py | reports/HYPOTHESIS_OLD_SAMPLE_REPORT.md | Runner opens virtual positions; live TP/SL update loop is not complete. |
| Task 4A — Session Normalization | DONE | src/session_classifier.py, src/signal_adapter.py | reports/HYPOTHESIS_OLD_SAMPLE_REPORT_SESSION_NORMALIZED.md, reports/OLD_SAMPLE_SESSION_NORMALIZATION_SUMMARY.md | Fixes labels only; no production rule. |
| Task 4B — Hypothesis Coverage Audit | DONE | reports/HYPOTHESIS_COVERAGE_AUDIT.* | reports/HYPOTHESIS_COVERAGE_AUDIT.md, reports/HYPOTHESIS_COVERAGE_AUDIT.json | No Research Pack added in 4B by user instruction. |
| Task 4C — Research Pack 2 | DONE for old-sample research | src/hypothesis_registry.py, src/research_pack2.py, config/hypotheses.yaml, tests/test_hypothesis_registry.py | reports/RESEARCH_PACK_2_REPORT.md, reports/RESEARCH_PACK_2_REPORT.json | Research Pack 2 is isolated from default runtime registry; old-sample results are not production rules. |

## Hypothesis System Status

- `config/hypotheses.yaml` contains `69` hypothesis IDs.
- default runtime `HypothesisRegistry()` exposes `15` hypotheses.
- Research Pack 2 is available only with `include_research_pack_2=True` and report runner; it totals `69` hypotheses.
- Research Pack 2 old-sample report status: `READY`.
- evaluated/skipped old-sample trades: `98/0`.
- duplicate/equivalent mask groups in Research Pack 2 report: `14`.

### Best Old-Sample Candidates

| hypothesis | trades | expectancy_R | net_R | <20 sample warning |
| --- | --- | --- | --- | --- |
| allow_only_continuation | 4 | 1.5 | 6.0 | True |
| allow_continuation_only_rsi_40_65 | 4 | 1.5 | 6.0 | True |
| allow_us_continuation_only | 2 | 1.5 | 3.0 | True |
| allow_rebound_only_if_htf_not_short | 6 | 0.25 | 1.5 | True |
| hour_20_23_msk | 4 | 0.25 | 1.0 | True |
| allow_us_mid_rsi_only | 23 | 0.1957 | 4.5 | False |
| score_90_plus | 27 | 0.0185 | 0.5 | False |
| allow_score_90_plus | 27 | 0.0185 | 0.5 | False |

### Toxic Old-Sample Filters/Zones

| hypothesis | trades | expectancy_R | net_R | <20 sample warning |
| --- | --- | --- | --- | --- |
| hour_10_14_msk | 13 | -0.8077 | -10.5 | True |
| hour_14_17_msk | 20 | -0.75 | -15.0 | False |
| score_70_80 | 29 | -0.7414 | -21.5 | False |
| market_mode_extreme_reversion | 17 | -0.7059 | -12.0 | True |
| ban_pullback_impulse_if_htf_short | 30 | -0.5 | -15.0 | False |
| atr_low_bucket | 33 | -0.4697 | -15.5 | False |
| allow_only_unknown | 27 | -0.4444 | -12.0 | False |
| allow_only_rebound | 67 | -0.403 | -27.0 | False |

### Why Old-Sample Results Cannot Move To Production

- The sample has only 98 evaluated old trades and several attractive candidates have fewer than 20 trades.
- The old sample is retrospective and can overfit to market regime, symbols, and journal quirks.
- Production rejected signals are not fully replayed with outcome, so saved-loss/missed-profit claims remain incomplete.
- Research Pack 2 is deliberately isolated from default live runtime.
- No automatic production rule changes are allowed; human review and future live paper/new production sample are required.

## Live Paper Readiness Matrix

| component | exists | where | currently does | missing | risk |
| --- | --- | --- | --- | --- | --- |
| Binance public market data client | yes | src/binance_data.py | GET /fapi/v1/klines and /time through public Binance Futures endpoints; no keys. | Retry/backoff/rate-limit policy and symbol metadata validation. | low |
| 15m candle polling / closed-candle loop | partial | src/live_research_engine.py | Polls latest klines, filters closed candles, deduplicates by symbol:timeframe close_time. | Dedicated closed-15m scheduler, persistence robustness, restart replay window, production-grade error handling. | medium |
| Symbol universe loader | partial | src/main.py CLI --symbols; config/research_config.yaml live_research.symbols | Accepts manual symbols and config defaults. | Validated universe file, liquidity filters, per-symbol enable/disable, Telegram visibility. | medium |
| Indicator calculation | partial | src/signal_adapter.py | Computes simple RSI, ATR pct, MA fast/slow for simplified live signal. | Production-like indicators/features and exact market-mode/HTF context. | medium |
| Signal candidate builder | partial | src/signal_adapter.py::signal_from_klines | Builds simplified MA/ATR signal candidates from public candles. | Production-like candidate logic; currently can emit SHORT despite MVP asking LONG-only unless constrained. | high |
| Production-like signal candidate model | partial | src/order_models.py::SignalCandidate | Typed candidate with symbol, timeframe, direction, entry, tp, sl, rr, RSI, ATR, phase, session, setup, HTF. | Schema versioning, explicit source metadata, validation constraints, feature completeness. | medium |
| Hypothesis portfolio evaluator | partial | src/hypothesis_runner.py | Evaluates enabled hypotheses and opens positions in separate portfolios. | Live Pack 2 selection policy, persistence across process restarts, open-position reconciliation. | medium |
| Virtual trade model | yes | src/order_models.py::Position/Trade; src/paper_broker.py | Represents virtual orders/positions/trades with R/PnL/fees/slippage. | Durable open trade store and schema version. | medium |
| Paper trade lifecycle | partial | src/paper_broker.py; src/hypothesis_runner.py; src/live_research_engine.py | Can open positions and close them if update_positions is called; historical replay can close from result. | Live engine does not yet call TP/SL tracking per candle for open positions. | high |
| TP/SL tracker | partial | src/paper_broker.py::update_positions/_resolve_exit | Resolves TP/SL against a candle, conservative same-candle policy. | Wired into live closed-candle loop for every open virtual position. | high |
| Open virtual trades storage | partial | src/portfolio.py in-memory; data/paper_portfolios snapshots | Open positions live in memory and counts go to runtime status. | Durable open_positions CSV/JSON across restarts. | high |
| Closed paper trades storage | yes | src/hypothesis_runner.py save_artifacts -> data/paper_trades/ | Writes closed trade rows to CSV. | Schema manifest and append/restart-safe strategy for 24/7. | medium |
| Per-hypothesis leaderboard | partial | src/portfolio.py metrics; src/demo_report_builder.py; reports/RESEARCH_PACK_2_REPORT.* | Computes metrics and candidate flags for reports. | Live rolling leaderboard endpoint/report and Telegram summary over current open/closed paper state. | medium |
| Daily/live report generator | partial | src/demo_report_builder.py; src/report_builder.py; Telegram latest_report | Builds demo/replay reports. | Scheduled daily report, live-specific open/closed status report, final flush report polish. | medium |
| Telegram status/report commands | partial | src/telegram_control.py, src/telegram_handlers.py, src/telegram_buttons.py | Read-only commands/buttons for start/stop/restart/status/latest/safety and portfolio/events. | Actual Telegram send of final stop report by bot loop may need integration verification; command queue requires running separate engine process. | medium |
| Safety guard against real/testnet orders | yes | src/execution_safety.py; src/testnet_broker.py; tests/test_execution_safety.py; config/research_config.yaml | Blocks production/real modes, real orders, and testnet without explicit flags/confirmation. | No known blocker; maintain tests for every new execution path. | low |

## Proposed Final Architecture

```text
Binance public candles
  -> closed 15m candle loop
  -> signal candidate builder
  -> features/metadata calculation
  -> hypothesis evaluator
  -> virtual trade open/reject
  -> TP/SL tracking
  -> paper trade close
  -> leaderboard/report
  -> Telegram status/report
```

## Future Safe Production Link

1. Sandbox observes current market independently.
2. Later, sandbox can import production candidate exports, not mutate production.
3. Sandbox compares hypothesis outcomes against paper results.
4. Human reviews evidence and approves or rejects candidate rules.
5. Only after that, production receives a separate surgical patch.
6. Sandbox must never automatically change production.

## Recommended Live Paper MVP Scope

Recommended path: **Option C first: public candles + paper lifecycle, then candidate builder.**

Reason: the current candidate builder is simplified and may not match production. Completing the paper lifecycle first gives a reliable engine for opening, tracking, closing, storing, and reporting virtual trades. Once that is stable, candidate generation can be improved or replaced by a production-like adapter without mixing lifecycle bugs with strategy logic.

Minimum next patch:

- public Binance klines only;
- 15m only;
- LONG-only or explicitly marked placeholder candidate mode;
- no private keys/account access/order endpoints;
- update open virtual positions on each closed candle;
- persist open positions and closed trades as CSV/JSON;
- basic per-hypothesis leaderboard;
- CLI status first, Telegram status after lifecycle is stable.

## Missing Components For Live Paper MVP

- Durable open virtual trades storage.
- Live-loop TP/SL tracker integration.
- Restart-safe portfolio reconstruction.
- Production-like LONG-only candidate adapter or explicit placeholder boundary.
- Symbol universe file/loader.
- Live rolling leaderboard and daily report.
- Telegram final report send verification.
- Clear config switch for default 15 hypotheses vs Research Pack 2 live validation.

## Risks And Blockers

- High: live positions currently may remain open forever because TP/SL tracker is not wired into live loop.
- High: open positions are in memory, so restart can lose active paper state.
- Medium: simplified signal builder can produce misleading paper evidence if treated as production-like.
- Medium: untracked reports/data/deployment state needs cleanup before GitHub.
- Low: safety guard blocks real/testnet modes, but every new execution path must keep using it.

## Test Status

No runtime code was changed in this audit. Tests are not required by the task unless code changes. The known correct project test command is:

```bash
./.venv/bin/python -m pytest -q
```

System `python3 -m unittest discover -s tests` is not reliable here because the system Python lacks project dependencies such as pandas/pytest.
