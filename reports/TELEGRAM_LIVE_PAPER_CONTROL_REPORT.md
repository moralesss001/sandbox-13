# Telegram Live Paper Control / Reporting Report

## 1. Executive Summary

Status: READY

Task 5D implemented a minimal Telegram control/reporting layer for Crypto13Research live paper. Telegram can now queue safe live paper start/stop commands and read runtime status, candidate source metadata, open virtual positions, closed paper trades, and shadow gate analytics.

Scope stayed sandbox-only. Production Crypto13 was not touched. No real orders, testnet orders, private Binance API, deployment, Docker/systemd, TP/SL/RR/risk/leverage changes, new entry strategy, or Research Pack 2 live activation were added.

## 2. What Changed

- Added live paper reporting helper for Telegram.
- Added `/live_start`, `/live_stop`, `/live_status`, `/source`, `/open_trades`, `/closed_trades`, `/gates` handlers.
- Added Telegram buttons for Source, Open Trades, Closed Trades, and Gates.
- `/live_start` queues `START_LIVE_PAPER` with `production_like_raw`, `15m`, `LONG_ONLY` metadata.
- Engine accepts `START_LIVE_PAPER` as a safe alias and marks control state as running when read.
- `/live_stop` queues safe stop only if live paper is running/start-requested/restart-requested.
- `/gates` reports shadow gate counters and saved/missed/allowed classifications from closed paper trades.
- Gate analytics now parse CSV boolean strings such as `False` correctly.

## 3. Files Changed

- `src/command_queue.py`
- `src/live_research_engine.py`
- `src/gate_analytics.py`
- `src/telegram_buttons.py`
- `src/telegram_control.py`
- `src/telegram_handlers.py`
- `tests/test_gate_analytics.py`
- `tests/test_telegram_handlers.py`

## 4. Files Created

- `src/telegram_live_paper.py`
- `reports/TELEGRAM_LIVE_PAPER_CONTROL_REPORT.md`
- `reports/TELEGRAM_LIVE_PAPER_CONTROL_REPORT.json`

## 5. Telegram Commands / Buttons Added

Commands: `/live_start`, `/live_stop`, `/live_status`, `/source`, `/open_trades`, `/closed_trades`, `/gates`.

Buttons added: Source, Open Trades, Closed Trades, Gates.

Existing buttons remain: Start Live Research, Stop Live Research, Restart Live Research, Live Status, Latest Report, Safety.

## 6. Start Live Paper Behavior

`/live_start` shows the existing confirmation flow. Confirming start queues `START_LIVE_PAPER` with payload: `candidate_source=production_like_raw`, `candidate_source_version=v1`, `timeframe=15m`, `direction=LONG_ONLY`, `mode=live_paper`, and symbols from current status or `config/research_config.yaml`.

If live paper is already `running` or `start_requested`, Telegram does not queue a duplicate command and returns current live status. Telegram does not spawn or kill external production processes. The separate sandbox engine reads the queue.

## 7. Stop Live Paper Behavior

`/live_stop` queues `STOP_LIVE_RESEARCH` only when the current control state is `running`, `start_requested`, or `restart_requested`.

If live paper is not running, Telegram returns: `Live paper is not running. No stop command queued.`

Stop remains sandbox-only. The engine is responsible for flushing paper portfolios, paper trades, hypothesis events, and final stop report when it reads the command.

## 8. Status Output

`/live_status` reads `data/runtime/runtime_status.json` and shows: mode, control_state, candidate_source, candidate_source_version, timeframe, direction, open virtual positions, closed trades, raw candidates, production allow/block counters, shadow blocked but tracked count, last processed candle time, last shadow block reasons, errors count, safety flags, and `edge_conclusions_allowed=false` warning.

Warning included: `Live paper is collecting evidence. Do not use this as production proof yet.`

## 9. Source Output

`/source` shows candidate source, version, placeholder flag, edge flag, direction support, description, `score_analytics_only=true`, `score_used_as_gate=false`, and `shadow_gates_enabled`.

## 10. Open Trades Output

`/open_trades` reads `data/paper_trades/open_positions.json` and shows up to 10 open virtual positions with symbol, direction, entry, TP, SL, opened_at, candidate_source, production_would_allow, production_block_reasons, and shadow_gate_block_reasons.

If none exist, it returns `No open virtual positions.`

## 11. Closed Trades Output

`/closed_trades` reads `data/paper_trades/closed_trades.csv` and shows the latest 5 closed paper trades with symbol, direction, entry, exit, result/R, close_reason, candidate_source, production_would_allow, and production_block_reasons.

If none exist, it returns `No closed paper trades yet.`

## 12. Gates Report Output

`/gates` shows gate_saved_from_loss, gate_missed_profit, gate_allowed_loss, gate_allowed_profit, production allow/block counters, shadow_blocked_but_tracked_count, shadow_gate_block_counts, and last_shadow_block_reasons.

If closed trades are missing, it returns `Not enough closed trades yet. Showing counters only.` No production conclusions are generated.

## 13. Safety Confirmations

- sandbox_only: true
- production_code_changed: false
- private_api_used: false
- real_orders_added: false
- testnet_orders_added: false
- deploy_changed: false
- docker_systemd_changed: false
- new_entry_strategy_added: false
- research_pack_2_live_enabled: false
- tp_sl_rr_risk_changed: false

Telegram safety output includes public_data_only, private_api_used, real_orders_enabled, testnet_orders_enabled, and production_code_changed.

## 14. Current Limitations

- Telegram queues start; it does not spawn the live engine process by itself.
- A separate sandbox engine process must be running to read `START_LIVE_PAPER` and `STOP_LIVE_RESEARCH`.
- `/gates` is evidence reporting only. It does not make edge or production conclusions.
- `production_like_raw` remains `edge_conclusions_allowed=false`.

## 15. How To Test Telegram Flow Locally

Run focused tests:

```bash
./.venv/bin/python -m pytest -q tests/test_telegram_handlers.py tests/test_gate_analytics.py
```

Covered local handler flows: status, source, open trades, closed trades, gates, safe start, duplicate start, safe stop, edge warning, and safety flags.

## 16. CLI Fallback Commands

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
./.venv/bin/python -m src.main status
```

## 17. What Remains Before Server Deploy

- Decide VPS/Railway process model.
- Add deployment runbook for engine plus Telegram bot processes.
- Configure Telegram token safely through environment variables.
- Verify command queue persistence on server filesystem.
- Verify long-running process supervision.
- Run first live paper observation protocol.

No Docker/systemd/Railway deployment changes were made in this task.

## 18. What Remains Before Edge Conclusions

- Collect at least the first 30 closed virtual trades.
- Continue to 60+ closed virtual trades before strong claims.
- Review gate saved/missed outcomes manually.
- Compare prospective paper results against old-sample replay.
- Do not move any rule to production automatically.

## 19. Test Results

Focused command: `./.venv/bin/python -m pytest -q tests/test_telegram_handlers.py tests/test_gate_analytics.py`

Result: `27 passed`

Full command: `./.venv/bin/python -m pytest -q`

Result: `105 passed, 1 environment warning`

The warning is the existing urllib3/LibreSSL environment warning and is not a test failure.
