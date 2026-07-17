# Crypto13Research — VPS 24/7 Live Research + Telegram Control Bot

## 1. Context

Crypto13Research is a sandbox/research system.

The accepted MVP already has:

- hypothesis replay;
- paper broker;
- paper portfolios;
- hypothesis runner;
- demo reports;
- safety guards;
- deployment skeleton.

The next task is to make the system server-operable for VPS 24/7 paper research and add a Telegram control panel.

Production Crypto13 is out of scope.
Do not inspect or modify Crypto13-main-4.

## 2. Main Server Mode

The primary server mode is:

```text
live-research paper mode
```

The research engine must be able to run 24/7 on VPS through systemd or Docker.

It must:

1. Connect to Binance public market data API.
2. Use REST polling MVP for live market data; leave WebSocket for future extension.
3. Process closed 15m candles.
4. Create signal candidates.
5. Run each signal candidate through all active hypotheses from `config/hypotheses.yaml`.
6. Maintain a separate paper portfolio for each hypothesis.
7. Open and close virtual trades only.
8. Save paper trades, hypothesis events, portfolio snapshots, live market logs, and reports.
9. Be controllable through Telegram control bot.
10. Run on VPS 24/7 through systemd or Docker.

## 3. Critical Safety

Forbidden:

- production trading;
- real Binance orders;
- production API keys;
- production DB writes;
- modifying production Crypto13;
- Telegram commands that enable real orders;
- Telegram commands that edit hypotheses directly.

Defaults must remain:

```text
API_MODE=paper
ALLOW_REAL_ORDERS=false
ALLOW_TESTNET_ORDERS=false
```

Telegram is only a control panel.
The research engine is a separate process.

## 4. Required Architecture

Separate the system into two processes:

```text
Process 1: live research engine
Process 2: Telegram control bot
```

They must not depend on each other being in the same process.

Recommended communication for MVP:

- shared status files;
- latest report files;
- paper portfolio snapshots;
- hypothesis event files;
- optional command queue file for safe commands.

Do not make Telegram directly place orders.

## 5. Required New/Updated Modules

Create or update:

```text
src/telegram_bot.py
src/telegram_handlers.py
src/telegram_control.py
src/telegram_config.py
src/runtime_status.py
src/command_queue.py
src/live_research_engine.py
src/main.py
src/execution_safety.py
```

If any module already exists, extend it instead of duplicating.

## 6. Telegram Bot MVP

Telegram bot commands:

```text
/start
/status
/safety
/hypotheses
/hypothesis <id>
/run_hypotheses
/latest_report
/suggestions
/portfolio
/events
/help
```

Allowed behavior:

- show current runtime status;
- show safety status;
- list active hypotheses;
- show hypothesis details;
- trigger hypothesis replay only if safe local CSV exists;
- show latest report path/summary;
- show latest suggestions;
- show latest paper portfolio snapshot;
- show recent hypothesis events.

Forbidden Telegram commands for MVP:

```text
/enable_hypothesis
/disable_hypothesis
/edit_hypothesis
/testnet_order
/real_order
```

Do not implement these commands.

## 7. Telegram Safety

`.env.example` must include:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_ID=
TELEGRAM_READ_ONLY=true
```

Telegram bot must refuse to start if:

- token is missing;
- allowed user id is missing;
- API_MODE is not paper;
- ALLOW_REAL_ORDERS is true;
- production trading is enabled.

Telegram handlers must reject users not in allowlist.

## 8. Live Research 24/7 Requirements

Update `live-research` so it can run continuously when explicitly requested.

Current safe smoke default can remain one iteration, but add explicit 24/7 option, for example:

```bash
python -m src.main live-research --symbols BTCUSDT,ETHUSDT --tf 15m --interval-sec 60 --run-forever
```

Requirements:

- process only closed candles;
- avoid duplicate processing of the same candle;
- persist runtime status;
- persist latest processed candle per symbol/timeframe;
- write heartbeat/status file;
- write errors to logs;
- continue after temporary Binance public API errors;
- never send real orders.

## 9. Runtime Status

Create status file, for example:

```text
data/runtime/status.json
```

Fields:

```text
mode
started_at
updated_at
symbols
timeframe
last_iteration_at
last_processed_candles
open_positions_count
closed_trades_count
latest_report_path
safety_status
errors
```

Telegram `/status` and `/safety` should read from this status.

## 10. Command Queue MVP

If Telegram triggers safe actions, use a simple queue file:

```text
data/runtime/commands.jsonl
```

Allowed queued commands:

```text
RUN_HYPOTHESIS_REPLAY
GENERATE_PAPER_REPORT
```

No trading commands.

Engine can process safe commands later, or Telegram can run safe read-only commands directly if simpler.

## 11. Deployment

Update deployment files:

```text
deployment/docker/Dockerfile
deployment/systemd/crypto13-live-research.service.example
deployment/systemd/crypto13-telegram-bot.service.example
deployment/README_DEPLOY.md
```

Systemd should have two services:

```text
crypto13-live-research.service
crypto13-telegram-bot.service
```

Defaults must be paper-only.
Systemd files are examples only, not auto-install scripts.

Docker should default to help/safe mode, not auto-live unless explicitly configured.

## 12. CLI Commands

Add/verify:

```bash
python -m src.main live-research --symbols BTCUSDT,ETHUSDT --tf 15m --interval-sec 60 --run-forever
python -m src.main telegram-bot
python -m src.main status
python -m src.main safety-status
```

`telegram-bot` must fail safely if Telegram env is missing.

## 13. Tests

Add tests:

```text
tests/test_telegram_config.py
tests/test_telegram_handlers.py
tests/test_runtime_status.py
tests/test_command_queue.py
tests/test_live_research_runtime.py
```

Verify:

- Telegram bot refuses missing token;
- Telegram bot refuses missing allowed user id;
- unauthorized user is rejected;
- read-only commands work;
- forbidden commands are not implemented;
- runtime status writes and reads correctly;
- command queue rejects trading commands;
- live-research avoids duplicate closed candle processing;
- live-research can run one safe iteration;
- production/real orders remain impossible.

## 14. What To Return To HQ

Coder must update `handoffs/CODER_REPORT.md` with:

- created files;
- changed files;
- commands run;
- pytest results;
- CLI smoke results;
- how to run live-research 24/7;
- how to run Telegram bot;
- how Telegram safety works;
- how engine and Telegram interact;
- deployment notes;
- remaining TODO;
- blockers/risks.

## 15. Acceptance Target

After this task, Crypto13Research should be ready for Tester to verify:

```text
VPS paper-only live research engine + Telegram read-only/control panel
```

No production deployment.
No real trading.
No testnet order placement.


## 16. Telegram Button Control Update

Telegram live research control must use buttons.

Required buttons:

```text
Start Live Research
Stop Live Research
Restart Live Research
Live Status
Latest Report
Safety
```

`/start_live` must show a confirmation screen before starting live research.

Stop must be manual:

```text
The live research process should run indefinitely until the user presses Stop Live Research or the server/service is stopped.
```

When `Stop Live Research` is pressed:

1. stop the live research process safely;
2. save current paper portfolios;
3. flush paper trades and hypothesis events to disk;
4. generate final stop report;
5. send report to Telegram.

Do not auto-stop live research after a fixed time by default.

Optional future feature:

```text
config-based max runtime
```

This must be disabled by default.

Implementation note:

- The safe local smoke default can still use one iteration for tests.
- The server 24/7 mode must use explicit `--run-forever` and must not auto-stop by fixed iteration count.
- Telegram buttons must enqueue/trigger only safe paper-mode controls.
- Buttons must never trigger real orders or testnet orders.


## 17. Railway Deployment Update

Deployment target is Railway from GitHub:

```text
GitHub repository -> Railway services
```

Railway is now the primary deployment path.
VPS/systemd remains a fallback/reference path only.

Railway-specific requirements:

1. Prepare the project so Railway can deploy it from a connected GitHub repository.
2. Support multiple Railway services from the same repo:
   - `crypto13-live-research` service;
   - `crypto13-telegram-bot` service.
3. Each service must have its own start command.
4. Dockerfile may be used if present, but default command must remain safe/help mode.
5. Add Railway deployment docs to `deployment/README_DEPLOY.md`.
6. Add an example Railway variables section.
7. Do not store Telegram token or secrets in git.
8. Railway variables must be used for secrets/config.
9. Paper mode must remain the default on Railway.
10. Railway live-research service must use explicit `--run-forever`.
11. Telegram bot service must run separately from the research engine.
12. If persistent files are required, document Railway Volume usage or the limitation of ephemeral storage.

Suggested Railway service start commands:

```bash
python -m src.main live-research --symbols BTCUSDT,ETHUSDT --tf 15m --interval-sec 60 --run-forever
python -m src.main telegram-bot
```

Required Railway variables:

```env
API_MODE=paper
ALLOW_REAL_ORDERS=false
ALLOW_TESTNET_ORDERS=false
BINANCE_PUBLIC_BASE_URL=https://fapi.binance.com
TELEGRAM_BOT_TOKEN=<set in Railway variables>
TELEGRAM_ALLOWED_USER_ID=<set in Railway variables>
TELEGRAM_READ_ONLY=true
```

Railway notes:

- Railway deploys services from GitHub repositories and can use a Dockerfile if found.
- Railway service variables are provided to build/runtime as environment variables.
- GitHub autodeploy may deploy latest commits, so unsafe defaults must never be committed.
- Long-running processes should be Railway persistent services.
- Any local filesystem persistence must be reviewed because platform storage can be ephemeral unless a volume is configured.

Coder must not create any production trading start command.
Coder must not create any start command that enables real orders or testnet orders.
