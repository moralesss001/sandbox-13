# Start Telegram Control Process

## Railway Primary Mode

Do not run Telegram as a Railway Pre-deploy Command.

Railway Start Command:

```bash
python -m src.main run-all
```

Pre-deploy Command: empty

`run-all` starts Telegram and the live paper engine in one service. Telegram should remain alive after `/live_stop` so the user can request `/live_start` again.

## Required Environment

Set environment values according to `ENV_EXAMPLE.md` before starting the service.

Required by current sandbox code:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_ID`
- `TELEGRAM_READ_ONLY=true`
- `API_MODE=paper`
- `ALLOW_REAL_ORDERS=false`
- `PRODUCTION_TRADING_ENABLED=false`

## Local Fallback Command

Use this only for local Telegram smoke testing:

```bash
./.venv/bin/python -m src.main telegram-bot
```

Smoke command:

```bash
./.venv/bin/python -m src.main telegram-bot --once
```

## Telegram Commands To Check

- `/live_status`
- `/source`
- `/open_trades`
- `/closed_trades`
- `/gates`

## Limitation

Telegram queues sandbox control commands and reads files. In Railway, `run-all` supervises the engine in the same service. In local fallback mode, if Telegram says a command was queued but status does not change, check the engine process and `data/runtime/commands.jsonl`.
