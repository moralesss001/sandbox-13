# Environment Example

Use placeholders only. Do not commit real secrets.

```bash
TELEGRAM_BOT_TOKEN=replace_me
TELEGRAM_ALLOWED_USER_ID=replace_me
TELEGRAM_READ_ONLY=true

API_MODE=paper
ALLOW_REAL_ORDERS=false
PRODUCTION_TRADING_ENABLED=false

CRYPTO13_MODE=sandbox_live_paper
BINANCE_DATA_MODE=public_only
REAL_ORDERS_ENABLED=false
TESTNET_ORDERS_ENABLED=false
PRIVATE_API_ENABLED=false
```

## Notes

- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USER_ID` are used by `src/telegram_config.py`.
- `API_MODE` must stay `paper`.
- `TELEGRAM_READ_ONLY` must stay `true`.
- `ALLOW_REAL_ORDERS` must stay `false`.
- `PRODUCTION_TRADING_ENABLED` must stay `false`.
- `TELEGRAM_ALLOWED_CHAT_ID` is not the current sandbox variable name; use `TELEGRAM_ALLOWED_USER_ID` unless code changes later.

## Forbidden

- No Binance private API keys.
- No production credentials.
- No real tokens in committed docs.
- No `.env` with real values in the repository.
