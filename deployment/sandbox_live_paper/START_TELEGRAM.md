# Start Telegram Control Process

Telegram control is implemented through the sandbox CLI.

## Required Environment

Set environment values according to `ENV_EXAMPLE.md` before starting the bot.

Required by current sandbox code:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_ID`
- `TELEGRAM_READ_ONLY=true`
- `API_MODE=paper`
- `ALLOW_REAL_ORDERS=false`
- `PRODUCTION_TRADING_ENABLED=false`

## Start Command

```bash
./.venv/bin/python -m src.main telegram-bot
```

## Smoke Command

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

Telegram queues sandbox control commands and reads files. It does not guarantee the engine process is already running. If Telegram says a command was queued but status does not change, check the engine process and `data/runtime/commands.jsonl`.
