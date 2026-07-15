# Sandbox Live Paper Runbook

## What Runs

Railway should run one sandbox service. The single service starts both components inside one Python process:

1. Telegram bot/control loop.
2. Live paper engine using `production_like_raw`.

Railway Start Command:

```bash
python -m src.main run-all
```

Pre-deploy Command: empty

Do not use `python -m src.main telegram-bot` as a Railway Pre-deploy Command. Telegram must run in the service runtime so it stays alive after `/live_stop`.

Separate `telegram-bot` and `live-research` commands remain available only as local fallback commands.

## Start Order

1. Check environment values using `ENV_EXAMPLE.md`.
2. Set Railway Start Command to `python -m src.main run-all`.
3. Leave Railway Pre-deploy Command empty.
4. Deploy the service.
5. In Telegram, check `/live_status`.
6. In Telegram, check `/source`.
7. In Telegram, check `/gates`.

## Runtime Paths

- Runtime status: `data/runtime/runtime_status.json`
- Command queue: `data/runtime/commands.jsonl`
- Open virtual positions: `data/paper_trades/open_positions.json`
- Closed paper trades: `data/paper_trades/closed_trades.csv`
- Reports: `reports/`

## CLI Fallback Commands

Railway dry-run plan:

```bash
python -m src.main run-all --dry-run
```

Safe one-iteration engine smoke:

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
```

Runtime status:

```bash
./.venv/bin/python -m src.main status
```

Telegram fallback:

```bash
./.venv/bin/python -m src.main telegram-bot
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

- `run-all` is the primary Railway runtime.
- `run-all` writes `mode=sandbox_run_all` and `runtime_layout=single_service` to runtime status.
- `Stop Live Research` stops the live engine safely, flushes paper artifacts, and leaves Telegram available for status and restart.
- Do not touch production Crypto13 processes.
