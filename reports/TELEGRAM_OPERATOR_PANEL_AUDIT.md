# Telegram Operator Panel Audit

## 1. Executive Summary

Status: **READY**

Task 5H.1 simplified the existing Telegram interface into a six-button operator panel. The patch reuses the current lifecycle queue, Task 5G storage, authorization, export allowlist, stable IDs, and deduplication. No trading or deployment behavior was changed.

## 2. Scope Confirmation

- Repository: `moralesss001/sandbox-13`
- Scope: sandbox Telegram operator UI only
- Research Sessions or Session IDs: not added
- Runtime storage paths and persistence: unchanged
- Candidate source, entry logic, TP, SL, RR, risk, gates, and hypotheses: unchanged
- Production, Railway configuration, Docker, systemd, real orders, testnet orders, and private Binance API: untouched

## 3. Previous UX Problems

The old main menu exposed lifecycle controls together with Source, Open Trades, Closed Trades, Gates, Safety, Latest Report, and Export. Stop had no confirmation, operational status exposed absolute paths and internal fields, and export had no transport-level delivery result.

## 4. Main Menu

The main keyboard now contains only:

1. `▶ Start Research`
2. `⏹ Stop Research`
3. `📊 Status`
4. `📦 Export Data`
5. `⚙ Settings`
6. `🧪 Diagnostics`

Restart remains available inside Diagnostics and through `/live_restart`.

## 5. Start Flow

Start uses the existing `START_LIVE_PAPER` safe command. The operator first sees source `production_like_raw v1`, mode `15m LONG_ONLY`, `PAPER ONLY`, and real orders `OFF`, with Confirm Start and Cancel buttons. A second start request returns `Research is already running.` and does not enqueue a second worker.

## 6. Stop Flow

Stop now requires Confirm Stop or Cancel. Confirmation reuses the existing `STOP_LIVE_RESEARCH` queue, stop-report creation, and engine flush lifecycle. Telegram remains online. Because engine shutdown is asynchronous, the immediate truthful acknowledgement is `Research stop requested.`; Status shows `Research Stopping` until the engine records `stopped`, then shows `Research Stopped`.

## 7. Status Output

The Status button and `/status` use the short operator view. It shows operator state, runtime duration, current-run raw candidates, current open positions, lifetime closed trades, error count, source/version, timeframe/direction, and `PAPER ONLY`. It omits paths, tracebacks, command queues, safety dictionaries, and shadow-reason lists.

`/live_status` remains a technical compatibility command and opens Diagnostics.

## 8. Settings Output

Settings is read-only and shows source/version, timeframe, direction, symbols, RR or `N/A`, enabled hypotheses count, enabled Shadow Gates count, and paper-only safety. It has no controls for TP, SL, RR, symbols, hypotheses, gates, risk, or source changes.

## 9. Diagnostics Output

Diagnostics contains runtime mode/layout, control and engine state, canonical runtime paths and existence flags, last candle, last error class, production allow/block counters, shadow tracked count, and only the latest shadow reason plus count. Restart is available from this secondary screen.

## 10. Export Data Behavior

The existing Task 5G exporter and allowlist are reused; no ZIP was added. Telegram sends the prepared allowlisted documents individually, tracks each transport attempt, and then reports actual `Sent` and `Missing` basenames. Secrets and `.env` remain excluded.

## 11. Backward Compatibility

Existing commands and callbacks for Source, Open Trades, Closed Trades, Gates, Safety, Latest Report, hypotheses, portfolio, events, and export remain implemented. They were removed only from the main keyboard. `/start_live` remains an alias, `/live_status` is Diagnostics, and `/live_restart` is available.

## 12. Files Changed

- `src/telegram_buttons.py`
- `src/telegram_bot.py`
- `src/telegram_control.py`
- `src/telegram_export.py`
- `src/telegram_handlers.py`
- `tests/test_live_paper_data_integrity.py`
- `tests/test_telegram_bot_export.py`
- `tests/test_telegram_handlers.py`

## 13. Files Created

- `reports/TELEGRAM_OPERATOR_PANEL_AUDIT.md`
- `reports/TELEGRAM_OPERATOR_PANEL_AUDIT.json`

## 14. Verification Results

All commands used the existing external sandbox virtual environment; no environment or deployment files were modified.

| Command | Exit | Result |
|---|---:|---|
| `python -m src.main --help` | 0 | CLI available; existing commands include `run-all`, `telegram-bot`, replay, live research, status, and safety status |
| `python -m src.main run-all --dry-run` | 0 | `single_service`; Telegram and live engine enabled; `PAPER ONLY`; real/testnet/private API false; Railway start command unchanged |
| `python -m pytest -q tests/test_run_all.py` | 0 | 11 passed |
| `python -m pytest -q tests/test_telegram_handlers.py` | 0 | 25 passed |
| `python -m pytest -q tests/test_telegram_bot_export.py` | 0 | 3 passed |
| `python -m pytest -q` | 0 | 137 passed, 1 warning |

The warning is the pre-existing urllib3/LibreSSL compatibility warning and is unrelated to Task 5H.1.

## 15. Remaining Risks

- Safe stop is asynchronous. Telegram acknowledges the request immediately and shows the final stopped state after the engine processes the queue; it does not falsely claim completion before that transition.
- Restart retains its existing direct lifecycle behavior and has no new confirmation because restart lifecycle changes were outside this surgical patch.
- Telegram network availability can still delay polling or delivery; export now reports per-file delivery failures without changing storage.

## 16. Safety Confirmations

- Research Sessions not added.
- Storage and Task 5G persistence not changed.
- Stable IDs and deduplication not changed.
- Trading logic not changed.
- Production not touched.
- Railway configuration not touched.
- Docker and systemd not touched.
- Real orders remain disabled.
- Testnet orders remain disabled.
- Private Binance API was not added or used.
