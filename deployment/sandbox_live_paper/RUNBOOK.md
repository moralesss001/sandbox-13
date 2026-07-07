# Sandbox Live Paper Runbook

## What Runs

Two sandbox processes are expected:

1. Sandbox live paper engine.
2. Telegram bot/control process.

Telegram queues commands and reads status. The engine reads the command queue and performs sandbox paper lifecycle work.

## Start Order

1. Check environment values using `ENV_EXAMPLE.md`.
2. Start Telegram/control process.
3. Start sandbox live paper engine.
4. In Telegram, check `/live_status`.
5. In Telegram, check `/source`.
6. In Telegram, check `/gates`.

## Runtime Paths

- Runtime status: `data/runtime/runtime_status.json`
- Command queue: `data/runtime/commands.jsonl`
- Open virtual positions: `data/paper_trades/open_positions.json`
- Closed paper trades: `data/paper_trades/closed_trades.csv`
- Reports: `reports/`

## CLI Fallback Commands

Safe one-iteration smoke:

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
```

Runtime status:

```bash
./.venv/bin/python -m src.main status
```

## Telegram Commands

- `/live_start`
- `/live_stop`
- `/live_status`
- `/source`
- `/open_trades`
- `/closed_trades`
- `/gates`

## Operating Notes

- Telegram does not have to spawn the engine.
- The engine should run as a separate sandbox process.
- Stop should be requested through `/live_stop` or by stopping the sandbox process manually.
- Do not touch production Crypto13 processes.
