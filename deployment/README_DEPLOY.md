# Sandbox Deploy Readiness Notes

This document describes the future intended shape for sandbox hosting. It does not perform deployment and does not change any remote repository.

Target path:

```text
GitHub -> Railway
```

Repository model:

- Use a separate GitHub repository for this sandbox export.
- Keep production Crypto13 in a different repository/project.
- Do not include secrets, runtime data, journals, candles, or private API keys.

Expected Railway services when a server deploy is approved later:

- `crypto13-live-research`
- `crypto13-telegram-bot`

## Railway Variables

Required safe variable defaults:

```bash
API_MODE=paper
TELEGRAM_READ_ONLY=true
ALLOW_REAL_ORDERS=false
PRODUCTION_TRADING_ENABLED=false
PRIVATE_API_ENABLED=false
REAL_ORDERS_ENABLED=false
TESTNET_ORDERS_ENABLED=false
```

Secret variables must be configured only in the hosting environment, not committed.

## Storage Warning

Railway filesystem storage can be ephemeral. Before using it for real observation, confirm where these files persist:

- `data/runtime/runtime_status.json`
- `data/runtime/commands.jsonl`
- `data/paper_trades/open_positions.json`
- `data/paper_trades/closed_trades.csv`

## Safety

- Sandbox paper mode only.
- Binance public candles only.
- No real orders.
- No testnet orders.
- No private Binance API.
- `edge_conclusions_allowed=false`.
