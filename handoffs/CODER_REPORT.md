# Coder Report

Use this file when `Crypto13Research Coder` returns implementation results to `Crypto13 HQ`.

## Latest Implementation Report

Status: `READY_FOR_TESTER`

Task title:

```text
Fix VPS/Telegram implementation gaps before Tester review.
```

## Scope completed

Fixed HQ review gaps for the VPS/Telegram layer:

```text
- Telegram now has inline control buttons.
- /start_live shows a confirmation screen before queuing live research start.
- Stop Live Research queues a safe stop, creates a stop report path, and tells Telegram where it is.
- Engine reads the explicit command queue and stops/restarts only through safe control commands.
- Railway deployment docs now describe the GitHub -> Railway two-service setup.
```

Production Crypto13 was not inspected or modified.
Crypto13-main-4 was not inspected.
Production `.env` and API keys were not used.
No real Binance orders were sent.
Testnet orders remain disabled.

## Changed files

```text
README.md
deployment/README_DEPLOY.md
handoffs/CODER_REPORT.md
src/command_queue.py
src/live_research_engine.py
src/telegram_bot.py
src/telegram_buttons.py
src/telegram_control.py
src/telegram_handlers.py
tests/test_command_queue.py
tests/test_deployment_docs.py
tests/test_telegram_handlers.py
```

New file:

```text
src/telegram_buttons.py
tests/test_deployment_docs.py
```

## Commands run

```text
.venv/bin/python -m pytest -p no:cacheprovider
.venv/bin/python -m src.main --help
.venv/bin/python -m src.main telegram-bot --once
.venv/bin/python -m src.main status
.venv/bin/python -m src.main safety-status
env PYTHONPYCACHEPREFIX=/private/tmp/crypto13_pycache .venv/bin/python -m compileall -q src tests
```

## Pytest result

```text
55 passed, 1 warning in 0.37s
```

Warning:

```text
urllib3 warns that this macOS Python uses LibreSSL. Tests still passed.
```

Compile check:

```text
compileall src tests: OK
```

## CLI smoke results

Help command:

```text
CLI includes: replay, hypothesis-replay, live-research, fetch-klines, paper-report,
testnet-smoke, telegram-bot, status, safety-status.
```

Telegram missing-env safety:

```text
.venv/bin/python -m src.main telegram-bot --once
Telegram bot blocked safely: TELEGRAM_BOT_TOKEN is required for Telegram control bot
```

Runtime status:

```text
mode: paper
symbols: BTCUSDT, ETHUSDT
timeframe: 15m
open_positions: 20
closed_trades: 0
latest_report: data/demo_reports/demo_report_20260605_174308.md
errors: 0
```

Safety status:

```text
api_mode: paper
allow_real_orders: False
allow_testnet_orders: False
telegram_read_only: True
production_trading: disabled
```

## Button flow

Telegram now sends an inline keyboard from `/start`, `/status`, `/safety`, and other read-only screens.

Required buttons implemented:

```text
Start Live Research
Stop Live Research
Restart Live Research
Live Status
Latest Report
Safety
```

Button callbacks:

```text
Start Live Research -> confirmation screen
Confirm Start Live Research -> queues START_LIVE_RESEARCH
Stop Live Research -> queues STOP_LIVE_RESEARCH and creates stop report
Restart Live Research -> queues RESTART_LIVE_RESEARCH
Live Status -> reads data/runtime/status.json
Latest Report -> reads latest demo/stop report
Safety -> reads paper-only safety status
```

`/start_live` now shows confirmation before queuing any live-research control command.

Unauthorized users cannot use text commands or press buttons.

Forbidden trading buttons/callbacks are not present:

```text
real_order
testnet_order
enable_real_orders
enable_testnet_orders
```

## Stop Live Research flow

When `Stop Live Research` is pressed:

```text
1. Telegram handler verifies allowed user.
2. Telegram enqueues STOP_LIVE_RESEARCH in data/runtime/commands.jsonl.
3. Telegram writes a stop report immediately under data/demo_reports/stop_report_*.md.
4. Telegram updates runtime status to stop_requested and returns the stop report path.
5. The separate live-research engine reads commands.jsonl.
6. On STOP_LIVE_RESEARCH, the engine flushes paper trades, paper portfolio snapshots, and hypothesis events.
7. The engine writes engine_stop_report_*.md and exits safely.
```

This is a control path only. It does not send real orders or testnet orders.

## Explicit control path

Allowed queue commands:

```text
START_LIVE_RESEARCH
STOP_LIVE_RESEARCH
RESTART_LIVE_RESEARCH
RUN_HYPOTHESIS_REPLAY
GENERATE_PAPER_REPORT
```

Trading/order commands are rejected by `src/command_queue.py`.

## Server mode behavior

Smoke tests can still use:

```bash
.venv/bin/python -m src.main live-research --symbols BTCUSDT,ETHUSDT --tf 15m --interval-sec 60 --max-iterations 1
```

Server mode requires explicit:

```bash
.venv/bin/python -m src.main live-research --symbols BTCUSDT,ETHUSDT --tf 15m --interval-sec 60 --run-forever
```

With `--run-forever`, live research runs until:

```text
- STOP_LIVE_RESEARCH command is processed;
- RESTART_LIVE_RESEARCH command is processed;
- the service/process is stopped externally.
```

## Railway deployment notes

`deployment/README_DEPLOY.md` now documents GitHub -> Railway as the primary path:

```text
- separate GitHub repo for Crypto13Research;
- two Railway services from the same repo:
  - crypto13-live-research
  - crypto13-telegram-bot
- separate start commands;
- Railway Variables;
- storage/Volume vs ephemeral filesystem limitations;
- paper-only defaults.
```

Railway service commands:

```bash
python -m src.main live-research --symbols BTCUSDT,ETHUSDT --tf 15m --interval-sec 60 --run-forever
python -m src.main telegram-bot
```

Required Railway variables include:

```text
API_MODE=paper
ALLOW_REAL_ORDERS=false
ALLOW_TESTNET_ORDERS=false
TELEGRAM_READ_ONLY=true
TELEGRAM_BOT_TOKEN=<set in Railway, never commit>
TELEGRAM_ALLOWED_USER_ID=<your Telegram user id>
```

Storage note:

```text
Railway filesystem may be ephemeral unless a Volume is attached.
For persistent reports/snapshots, mount a Railway Volume for data/.
```

## Tests added / updated

```text
tests/test_command_queue.py
tests/test_deployment_docs.py
tests/test_telegram_handlers.py
```

Coverage added:

```text
- Telegram buttons exist.
- /start_live confirmation exists.
- unauthorized user cannot press buttons.
- forbidden trading buttons/callbacks do not exist.
- command queue accepts only safe control commands.
- Stop Live Research creates/requests final stop report behavior.
- Railway docs mention GitHub -> Railway and two-service setup.
```

## Remaining risks / TODO

```text
- Engine-side START_LIVE_RESEARCH currently marks control_state=running when processed by an already-running engine; starting a stopped Railway service still belongs to Railway/service orchestration.
- Stop report is generated immediately by Telegram and a second engine stop report is generated when the engine processes STOP.
- Queue entries are append-only; processed ids are tracked in runtime status. A future cleanup/rotation task would be useful.
- Telegram live bot was not started with a real token/user id during this fix pass.
- The previously pasted Telegram token should be rotated with BotFather.
```

## Suggested next step for HQ

```text
Send to Crypto13Research Tester.
Tester should verify button flow, /start_live confirmation, STOP queue/report behavior,
Railway docs, pytest, and safety boundaries.
```
