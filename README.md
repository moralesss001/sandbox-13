# Crypto13 Research Sandbox

Local research project for testing a future adaptive Crypto13 architecture without real capital, production database writes, trading API keys, or order execution.

The production Crypto13 project is a read-only reference only. Do not change it, do not run the production bot, and do not interfere with the active 15m RR 1.5 test.

## What This MVP Does

- Reads a CSV journal exported from Crypto13.
- Filters trades by timeframe, default `15m`.
- Normalizes results into `win` / `loss`.
- Calculates R when `entry`, `tp`, `sl`, and `result` are available.
- Builds shadow context: `rsi_zone`, `volatility_state`, session, strategy mode, risk mode.
- Decides what the adaptive architecture would have done: `ALLOW`, `NO_TRADE`, or `REDUCE_RISK`.
- Writes a Markdown report to `data/reports/`.
- Runs hypothesis replay with separate paper portfolios per hypothesis.
- Fetches Binance Futures public klines without API keys.
- Runs safe live research polling in paper mode with simplified live signals.
- Builds demo reports and hypothesis leaderboards.
- Provides a disabled-by-default testnet foundation.

## What This Project Never Does

- It does not trade.
- It does not send orders.
- It does not use real trading API keys.
- It does not write to production DB.
- It does not modify the production Crypto13 strategy.
- It does not auto-deploy the best hypothesis.

Production trading is disabled by code. Any production/live/real API mode raises:

```text
RuntimeError("Production trading is disabled in Crypto13Research")
```

## Setup

```bash
cd /path/to/Crypto13Research
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Journal Replay Mode

Put your exported CSV into `data/journals/`, for example:

```text
data/journals/signals.csv
```

Run:

```bash
python -m src.main replay --file data/journals/signals.csv --tf 15m
```

Optional report directory:

```bash
python -m src.main replay --file data/journals/signals.csv --tf 15m --out data/reports
```

Reports are saved as:

```text
data/reports/replay_report_YYYYMMDD_HHMMSS.md
```

## Hypothesis Replay Mode

Runs the required no-money flow:

```text
journal rows -> signal candidates -> hypothesis runner -> paper portfolios -> metrics -> leaderboard
```

Run:

```bash
python -m src.main hypothesis-replay --file data/journals/signals_export_1897339801.csv --tf 15m
```

Demo reports are saved to:

```text
data/demo_reports/demo_report_YYYYMMDD_HHMMSS.md
```

Paper artifacts:

```text
data/paper_trades/paper_trades_YYYYMMDD.csv
data/paper_portfolios/portfolio_snapshots_YYYYMMDD.csv
data/hypothesis_events/hypothesis_events_YYYYMMDD.csv
```

## Paper Mode vs Testnet Mode

Paper mode is the default. It uses virtual portfolios and virtual fills only.

Testnet mode is a future/demo execution foundation. It is disabled by default and cannot send a testnet order unless all of these are true:

- config uses a demo/testnet base URL;
- `allow_testnet_orders` is true;
- CLI includes `--confirm-testnet-order`.

Production Binance trading endpoints are never allowed in Crypto13Research.

## Live Research Paper Mode

Uses Binance Futures public REST market data. Public market data does not need API keys.

Safe smoke run:

```bash
python -m src.main live-research --tf 15m --interval-sec 60 --max-iterations 1
```

VPS 24/7 paper mode requires explicit `--run-forever`:

```bash
python -m src.main live-research --tf 15m --interval-sec 60 --run-forever
```

The engine writes runtime state to:

```text
data/runtime/status.json
```

It processes closed candles, tracks the last processed candle per symbol/timeframe, and avoids duplicate processing.

The live generator is simplified and always marks:

```text
signal_source = research_simplified_live
```

This matters because live research results from the simplified generator are not proof that production Crypto13 should change.

## Fetch Klines

Download public Binance Futures candles:

```bash
python -m src.main fetch-klines --symbol BTCUSDT --tf 15m --limit 500
```

Saved files live in:

```text
data/live_market/
```

## Paper Report

Print the latest paper portfolio snapshot:

```bash
python -m src.main paper-report
```

## Safety Status

Defaults are stored in `config/research_config.yaml` and `.env.example`:

```text
API_MODE=paper
ALLOW_REAL_ORDERS=false
ALLOW_TESTNET_ORDERS=false
```

Testnet smoke is expected to fail unless explicitly enabled and confirmed:

```bash
python -m src.main testnet-smoke --symbol BTCUSDT --tf 15m
```

Runtime status:

```bash
python -m src.main status
python -m src.main safety-status
```

## Telegram Read-Only Control Panel

Telegram is a separate process from the live research engine.

Run:

```bash
python -m src.main telegram-bot
```

Required env:

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_ID=
TELEGRAM_READ_ONLY=true
API_MODE=paper
ALLOW_REAL_ORDERS=false
ALLOW_TESTNET_ORDERS=false
```

Allowed Telegram commands:

```text
/start
/start_live
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

Forbidden commands are not implemented:

```text
/enable_hypothesis
/disable_hypothesis
/edit_hypothesis
/testnet_order
/real_order
```

Telegram does not send orders and does not edit hypotheses. It reads shared files and can enqueue only safe commands:

```text
RUN_HYPOTHESIS_REPLAY
GENERATE_PAPER_REPORT
```

Queue file:

```text
data/runtime/commands.jsonl
```

Telegram also exposes inline buttons:

```text
Start Live Research
Stop Live Research
Restart Live Research
Live Status
Latest Report
Safety
```

`/start_live` and the `Start Live Research` button show a confirmation screen first. The confirmation queues only `START_LIVE_RESEARCH`; it does not start trading, testnet, or production execution.

`Stop Live Research` queues `STOP_LIVE_RESEARCH`, writes a stop report path back to Telegram, and lets the separate live research engine flush paper artifacts and exit safely when it processes the queue.

## Railway Single Service

Railway should run one sandbox service that starts Telegram control and the live paper engine together.

Railway Start Command:

```bash
python -m src.main run-all
```

Pre-deploy Command: empty

Do not use `python -m src.main telegram-bot` as Railway Pre-deploy Command. Telegram must stay in the main runtime process, not in a pre-deploy step.

Useful dry-run before deploy:

```bash
python -m src.main run-all --dry-run
```

`run-all` defaults:

```text
UNIVERSE=crypto13_contract_v1 (46 pairs from src/universe.py)
CRYPTO13_TIMEFRAME=15m
CRYPTO13_CANDIDATE_SOURCE=production_like_raw
CRYPTO13_INTERVAL_SEC=60
```

`CRYPTO13_SYMBOLS` no longer narrows the default runtime universe. Symbols that are unavailable from the public market-data source remain configured and are reported separately in runtime status.

Runtime status is written to:

```text
data/runtime/runtime_status.json
```

Safety metadata remains fixed to paper-only:

```text
real_orders_enabled=false
testnet_orders_enabled=false
private_api_used=false
```

`/live_stop` stops only the live paper engine and flushes paper artifacts. Telegram remains available in the same Railway service so `/live_start` can request a restart.

Legacy separate commands remain available as local fallback, but Railway should use `run-all`.

## VPS / Server Foundation

Deployment examples live in:

```text
deployment/docker/Dockerfile
deployment/systemd/crypto13-live-research.service.example
deployment/systemd/crypto13-telegram-bot.service.example
deployment/README_DEPLOY.md
```

Docker defaults to:

```bash
python -m src.main --help
```

The systemd file is an example only and should not be enabled without HQ review.

## Expected CSV Columns

The loader works even when some fields are missing. Best results come from exports with:

```text
timeframe, result, entry, tp, sl, rsi, atr_pct, market_phase,
setup_type, trend_htf, impulse_before_entry, reason,
confidence_factors, rr_ratio, session_msk, hour_msk
```

Result values are normalized:

```text
TP / WIN / profit / take_profit -> win
SL / LOSS / loss / stop_loss -> loss
```

## Live Shadow Mode

`LiveShadowEngine` is only a safe skeleton now. It writes local virtual decisions to `data/shadow_logs/` and never opens trades or sends signals.

If the Mac is off, local live shadow mode is off too. For 24/7 shadow tracking, a VPS will be needed later.

## Backtest Mode

`BacktestEngine` is a safe skeleton for future candle-based testing via Binance Futures public market data. It has no trading-key support.

## Research Rule

Research first, then conclusions, then decision, and only then any separate production Crypto13 change.

Best hypothesis does not mean production deploy. It means at most: candidate for HQ review and possible testnet/demo validation.

## Sub-Agent Workflow

This project uses one active user-facing chat:

```text
Crypto13 HQ
```

Coder and Tester are sub-agent roles orchestrated from HQ:

```text
Crypto13 HQ -> Coder sub-agent -> Tester sub-agent -> Crypto13 HQ
```

Coordination files:

```text
PROJECT_CONTEXT.md
docs/CHAT_PROTOCOL.md
docs/SUBAGENT_WORKFLOW.md
handoffs/HQ_OUTBOX.md
handoffs/CODER_REPORT.md
handoffs/TESTER_REPORT.md
handoffs/DECISION_LOG.md
```

`handoffs/` remains as audit trail and fallback, but normal operation is managed by HQ through sub-agents.
