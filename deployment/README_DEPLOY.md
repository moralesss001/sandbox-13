# Crypto13Research Deployment Notes

This project is deployable as a paper-only research system.

Production trading is disabled. Real Binance orders and testnet orders are not part of this deployment.

## Defaults

```text
API_MODE=paper
ALLOW_REAL_ORDERS=false
ALLOW_TESTNET_ORDERS=false
TELEGRAM_READ_ONLY=true
UNIVERSE=crypto13_contract_v1 (46 pairs from src/universe.py)
CRYPTO13_TIMEFRAME=15m
CRYPTO13_CANDIDATE_SOURCE=production_like_raw
CRYPTO13_INTERVAL_SEC=60
```

## Primary Path: GitHub -> Railway

Recommended HQ-controlled deployment path:

1. Create a separate GitHub repository for `Crypto13Research`.
2. Push only this sandbox project to that repository.
3. Connect the GitHub repository to Railway.
4. Create one Railway service from the repo.
5. Set Railway Start Command to `python -m src.main run-all`.
6. Leave Railway Pre-deploy Command empty.

Do not connect Railway to production Crypto13 or `Crypto13-main-4`.

## Railway Service: crypto13-research-sandbox

Railway Start Command:

```bash
python -m src.main run-all
```

Pre-deploy Command: empty

Do not use `python -m src.main telegram-bot` as a Railway Pre-deploy Command.

Required Railway Variables:

```text
API_MODE=paper
ALLOW_REAL_ORDERS=false
ALLOW_TESTNET_ORDERS=false
TELEGRAM_READ_ONLY=true
TELEGRAM_BOT_TOKEN=<set in Railway, never commit>
TELEGRAM_ALLOWED_USER_ID=<your Telegram user id>
CRYPTO13_TIMEFRAME=15m
CRYPTO13_CANDIDATE_SOURCE=production_like_raw
CRYPTO13_INTERVAL_SEC=60
```

The configured universe is the fixed 46-pair owner contract in `src/universe.py`; `CRYPTO13_SYMBOLS` is not a deployment override.

Optional variables:

```text
BINANCE_PUBLIC_BASE_URL=https://fapi.binance.com
CRYPTO13_DATA_ROOT=data
```

Telegram is a read-only/control panel. It must not execute trading commands.

## Runtime Files and Storage

The engine and Telegram communicate through files inside the same Railway service:

```text
data/runtime/runtime_status.json
data/runtime/commands.jsonl
data/demo_reports/
data/paper_portfolios/
data/hypothesis_events/
data/paper_trades/
data/live_market/
```

Railway filesystem may be ephemeral unless a Volume is attached.

Options:

- Attach a Railway Volume mounted at the project `data/` path if persistent reports are required.
- Without a Volume, generated reports and snapshots can disappear on redeploy/restart.
- For MVP validation, ephemeral storage is acceptable only if HQ understands reports are temporary.

## Local Smoke Commands

Dry-run the Railway supervisor plan:

```bash
python -m src.main run-all --dry-run
```

Check CLI fallback commands:

```bash
python -m src.main live-research --tf 15m --candidate-source production_like_raw --max-iterations 1
python -m src.main telegram-bot --once
```

## Docker

The Docker image can run the same service command:

```bash
python -m src.main run-all
```

Railway should still set the explicit Start Command.

## Systemd Alternative

Systemd files are legacy examples only:

```text
deployment/systemd/crypto13-live-research.service.example
deployment/systemd/crypto13-telegram-bot.service.example
```

They are not autostart scripts and should be reviewed by HQ before use.

## Safety

Testnet execution remains disabled unless HQ explicitly approves a future testnet step.

Production trading is disabled in Crypto13Research.

Forbidden:

```text
ALLOW_REAL_ORDERS=true
ALLOW_TESTNET_ORDERS=true
API_MODE=production
API_MODE=live
production Binance trading endpoints
```
