# Start Sandbox Live Paper Engine

## Railway Primary Command

Railway should start the full sandbox runtime with one command:

```bash
python -m src.main run-all
```

Pre-deploy Command: empty

This single service starts the Telegram control loop and the live paper engine using `production_like_raw`.

## Dry Run

```bash
python -m src.main run-all --dry-run
```

Expected defaults:

```text
UNIVERSE=crypto13_contract_v1 (46 pairs from src/universe.py)
CRYPTO13_TIMEFRAME=15m
CRYPTO13_CANDIDATE_SOURCE=production_like_raw
CRYPTO13_INTERVAL_SEC=60
```

## Local Engine Fallback

Use this only for local smoke testing, not as the Railway primary command:

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --run-forever --interval-sec 60
```

Safe one-iteration smoke:

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
```

## Important

- Engine process is sandbox-only.
- Production processes must not be touched.
- Candidate source must stay `production_like_raw`.
- Timeframe must stay `15m`.
- Direction policy must stay `LONG_ONLY`.
- `edge_conclusions_allowed=false`.
- Real orders remain disabled.
- Testnet orders remain disabled.
