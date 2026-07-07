# Live Paper Lifecycle MVP Report

## Status

READY

Task 5B implemented a local live paper lifecycle MVP inside Crypto13Research only. Production Crypto13 was not touched. No real orders, testnet orders, private Binance API calls, deployment, Docker, systemd, GitHub publishing, new hypotheses, or Research Pack 2 live activation were added.

## Implemented Scope

1. Closed 15m candle lifecycle is now wired into `LiveResearchEngine`.
2. Existing open virtual positions are restored before polling starts.
3. On each newly closed candle, open positions are updated before any new candidate is opened.
4. TP/SL exits use the existing `PaperBroker.update_positions()` and `_resolve_exit()` logic.
5. Same-candle TP/SL conflict policy remains conservative through the existing broker policy.
6. Closed virtual trades are appended to durable CSV storage.
7. Open virtual positions are persisted after close/open lifecycle changes.
8. Runtime status is written to a Telegram-compatible status file.
9. MVP is limited to `15m`.
10. MVP is limited to `LONG` candidates.
11. `SHORT` candidates are ignored and counted, not opened.

## Files Changed

- `src/live_research_engine.py`
- `src/paper_broker.py`
- `src/runtime_status.py`
- `src/telegram_control.py`

## Files Created

- `src/live_paper_storage.py`
- `tests/test_live_paper_lifecycle.py`
- `reports/LIVE_PAPER_LIFECYCLE_MVP_REPORT.md`
- `reports/LIVE_PAPER_LIFECYCLE_MVP_REPORT.json`

## Storage Paths

- Open positions: `data/paper_trades/open_positions.json`
- Closed trades: `data/paper_trades/closed_trades.csv`
- Runtime status: `data/runtime/runtime_status.json`

## Runtime Status Fields

The runtime status now includes:

- `mode: live_paper_lifecycle_mvp`
- `interface_target: telegram`
- `cli_is_fallback: true`
- `timeframe: 15m`
- `direction: LONG`
- `candidate_mode: simplified_or_existing`
- `open_virtual_positions_count`
- `closed_trades_count`
- `ignored_short_candidates_count`
- `storage_paths`
- `checkpoint_progress`
- `research_pack_2_enabled: false`
- `safety_status.public_data_only: true`
- `safety_status.private_api_used: false`
- `safety_status.real_orders_enabled: false`
- `safety_status.testnet_orders_enabled: false`

## Local Commands

Run one safe smoke iteration:

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --max-iterations 1
```

Run continuously until manual stop/service stop:

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT,ETHUSDT --tf 15m --run-forever --interval-sec 60
```

Check runtime status:

```bash
./.venv/bin/python -m src.main status
```

Check safety status:

```bash
./.venv/bin/python -m src.main safety-status
```

Local CLI stop is still process-level fallback, for example `Ctrl+C`. Telegram Stop already queues a stop command through the existing control queue, and the engine flushes artifacts and writes a final stop report when it reads that command.

## Telegram Preparation

Telegram remains the target interface. The lifecycle writes the status file that Telegram control reads:

```text
data/runtime/runtime_status.json
```

The Telegram control panel path was updated from `data/runtime/status.json` to `data/runtime/runtime_status.json`.

## Safety Confirmations

- Production Crypto13 was not touched.
- Real Binance orders were not added.
- Testnet orders were not added.
- Binance private API was not added.
- `.env` was not changed.
- Research Pack 2 remains disabled for live paper by default.
- Strategy logic, RR, TP, SL, leverage, and hypotheses were not changed.

## Remaining Work

Task 5B intentionally does not complete:

- Full Telegram dashboard.
- VPS deployment.
- Docker/systemd.
- WebSocket market data.
- Production-grade candidate builder.
- Multi-direction live paper.
- Research Pack 2 live activation.
- Leaderboard/edge analytics for live paper.

These remain future Task 5C/5D items, not part of this MVP.

## Tests

Commands run:

```bash
./.venv/bin/python -m pytest -q tests/test_paper_broker.py tests/test_live_research_runtime.py tests/test_live_paper_lifecycle.py tests/test_runtime_status.py tests/test_telegram_handlers.py
./.venv/bin/python -m pytest -q
```

Results:

- Targeted tests: `22 passed`
- Full tests: `65 passed`
- Warning: local urllib3/OpenSSL warning from the Python environment, not a test failure.

