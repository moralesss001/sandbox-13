# Tester Report

Use this file when `Crypto13Research Tester` returns validation results to `Crypto13 HQ`.

## Latest Validation Report

Status: `PASSED_WITH_NOTES`

Task tested:

```text
Validate Demo/Paper Trading + Hypothesis Engine MVP implemented by Coder.

Scope tested from HQ_OUTBOX.md:
- Coder created/changed files exist.
- pytest passes inside Crypto13Research.
- CLI help exists for hypothesis-replay, live-research, fetch-klines, paper-report, testnet-smoke.
- hypothesis-replay can generate a demo report from the local journal CSV.
- paper-report can read the latest portfolio snapshot.
- testnet-smoke is blocked without ALLOW_TESTNET_ORDERS and --confirm-testnet-order.
- execution_safety blocks production/live/real trading modes and allow_real_orders.
- paper broker opens virtual positions only, closes TP/SL, and uses conservative SL-first intrabar policy.
- hypothesis registry includes the requested hypotheses.
- signal_source is preserved for journal_replay and research_simplified_live.
- demo report includes leaderboard, safety status, blocked trades, missed wins, saved losses, and candidates for testnet.

Skipped by explicit user safety instruction:
- Inspecting Crypto13-main-4 / production Crypto13.
```

Commands tested:

```text
sed -n '1,260p' PROJECT_CONTEXT.md
sed -n '1,300p' docs/CHAT_PROTOCOL.md
sed -n '1,300p' handoffs/HQ_OUTBOX.md
sed -n '1,300p' handoffs/CODER_REPORT.md
sed -n '1,260p' handoffs/TESTER_REPORT.md

# File existence check for all Coder-created files.
for f in .env.example .gitignore RESEARCH_ROADMAP.md deployment/README_DEPLOY.md deployment/docker/Dockerfile deployment/systemd/crypto13-live-research.service.example src/demo_report_builder.py src/execution_safety.py src/hypothesis_registry.py src/hypothesis_runner.py src/live_research_engine.py src/order_models.py src/paper_broker.py src/portfolio.py src/signal_adapter.py src/testnet_broker.py tests/test_execution_safety.py tests/test_hypothesis_registry.py tests/test_hypothesis_runner.py tests/test_paper_broker.py tests/test_portfolio_metrics.py tests/test_signal_adapter.py data/paper_trades/.gitkeep data/paper_portfolios/.gitkeep data/hypothesis_events/.gitkeep data/testnet_logs/.gitkeep data/demo_reports/.gitkeep data/live_market/.gitkeep; do test -e "$f" || echo "MISSING $f"; done

./.venv/bin/python -m pytest -q
./.venv/bin/python -m src.main hypothesis-replay --help
./.venv/bin/python -m src.main live-research --help
./.venv/bin/python -m src.main fetch-klines --help
./.venv/bin/python -m src.main paper-report --help
./.venv/bin/python -m src.main testnet-smoke --help
find data/journals -maxdepth 1 -type f -name '*.csv' -print | sort
find data/paper_portfolios -maxdepth 1 -type f -print | sort
find data/demo_reports -maxdepth 1 -type f -print | sort
./.venv/bin/python -m src.main hypothesis-replay --file data/journals/signals_export_1897339801.csv --tf 15m
./.venv/bin/python -m src.main paper-report
./.venv/bin/python -m src.main testnet-smoke --symbol BTCUSDT --tf 15m
sed -n '1,260p' data/demo_reports/demo_report_20260605_170504.md
sed -n '1,320p' src/hypothesis_registry.py
rg -n "signal_source|journal_replay|research_simplified_live" src tests data/demo_reports/demo_report_20260605_170504.md
rg -n "leaderboard|safety|blocked|missed|saved|candidate|testnet|ALLOW|BLOCK|REDUCE_RISK" data/demo_reports/demo_report_20260605_170504.md src/demo_report_builder.py
./.venv/bin/python -c "from src.execution_safety import assert_not_production;
for cfg in [{'mode':'production'}, {'mode':'live'}, {'api_mode':'real'}, {'allow_real_orders':'true'}]:
    try:
        assert_not_production(cfg)
    except RuntimeError as e:
        print('blocked', cfg, str(e))
    else:
        raise SystemExit(f'NOT BLOCKED {cfg}')"
./.venv/bin/python -m pytest -q tests/test_execution_safety.py tests/test_paper_broker.py tests/test_hypothesis_registry.py tests/test_signal_adapter.py
sed -n '1,260p' tests/test_paper_broker.py
sed -n '1,220p' tests/test_execution_safety.py
```

Passed checks:

```text
- All Coder-created files listed in handoffs/CODER_REPORT.md exist. The file existence check printed no MISSING lines.
- Full pytest passed: 33 passed in 1.14s.
- Focused safety/paper/hypothesis/signal tests passed: 9 passed in 0.16s.
- CLI help works for:
  - hypothesis-replay
  - live-research
  - fetch-klines
  - paper-report
  - testnet-smoke
- hypothesis-replay replayed 98 local journal signals and generated:
  data/demo_reports/demo_report_20260605_170504.md
- paper-report read latest portfolio snapshot:
  data/paper_portfolios/portfolio_snapshots_20260602.csv
- testnet-smoke without confirmation was blocked safely:
  Testnet orders are disabled: ALLOW_TESTNET_ORDERS=false
- execution_safety manually blocked configs:
  - {'mode': 'production'}
  - {'mode': 'live'}
  - {'api_mode': 'real'}
  - {'allow_real_orders': 'true'}
- Paper broker tests verify virtual open, TP close, SL close, and conservative intrabar SL-first behavior.
- Hypothesis registry includes all 15 hypotheses listed by Coder:
  baseline_rr15, ban_rsi_below_35, ban_rsi_below_38, ban_rsi_below_40,
  ban_unclear_europe_rebound, ban_overlap, ban_unclear_low_rsi,
  ban_low_rsi_europe, ban_rebound_europe, ban_unclear_europe,
  allow_only_mid_rsi, allow_only_continuation, allow_us_unknown,
  ban_unclear_overlap, ban_europe_low_rsi.
- signal_source is preserved in code/tests/report for:
  - journal_replay
  - research_simplified_live
- Demo report includes leaderboard, safety status, blocked trades, missed wins, saved losses, and candidates for testnet.
```

Failed checks:

```text
None.
```

Safety checks:

```text
- Real orders: PASS - no real orders were sent; execution_safety blocks allow_real_orders and production/live/real modes.
- Production API keys: PASS - production .env/API keys were not used or inspected.
- Production DB: PASS - no production DB access was performed.
- Production Crypto13 modifications: SKIPPED_BY_USER_INSTRUCTION - Crypto13-main-4 was not inspected because the current instruction explicitly says not to inspect it.
- Testnet order blocking: PASS - testnet-smoke blocked without ALLOW_TESTNET_ORDERS and --confirm-testnet-order.
- Production mode blocking: PASS - production/live/real configs raise RuntimeError("Production trading is disabled in Crypto13Research").
```

Reports verified:

```text
PROJECT_CONTEXT.md
docs/CHAT_PROTOCOL.md
handoffs/HQ_OUTBOX.md
handoffs/CODER_REPORT.md
handoffs/TESTER_REPORT.md
data/demo_reports/demo_report_20260605_170504.md
Existing Coder reports:
data/demo_reports/demo_report_20260602_202325.md
data/demo_reports/demo_report_20260602_202514.md
```

Risks found:

```text
- urllib3 emits a LibreSSL warning on this macOS Python. It did not block local tests or CLI help, but it remains an environment warning for future public Binance fetch checks.
- Production Crypto13 modification verification was intentionally not performed in this tester run because the current instruction explicitly forbids inspecting Crypto13-main-4.
- Testnet broker is still intentionally blocked/not implemented for real testnet order placement; this is safe and expected, but HQ must explicitly approve any future demo/testnet step.
- Candidate_for_testnet is a research/report flag only. It must not be treated as deployment approval.
```

Tester recommendation to HQ:

```text
Accept
```
