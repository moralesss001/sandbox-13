# Single Service Railway Runner Report

## Executive Summary

Status: READY

Task 5F adds one Railway runtime entrypoint:

```bash
python -m src.main run-all
```

Pre-deploy Command: empty

`run-all` starts Telegram control and the live paper engine inside one sandbox process. It uses `production_like_raw`, `15m`, `LONG_ONLY`, public market data only, and paper portfolios only.

## Runtime Defaults

```text
CRYPTO13_SYMBOLS=BTCUSDT,ETHUSDT
CRYPTO13_TIMEFRAME=15m
CRYPTO13_CANDIDATE_SOURCE=production_like_raw
CRYPTO13_INTERVAL_SEC=60
```

## Runtime Metadata

```text
mode=sandbox_run_all
runtime_layout=single_service
telegram_enabled=true
live_engine_enabled=true
candidate_source=production_like_raw
timeframe=15m
direction=LONG_ONLY
real_orders_enabled=false
testnet_orders_enabled=false
private_api_used=false
```

## Behavior

- Telegram bot/control loop runs in the same service.
- Live paper engine runs in the same service.
- `/live_stop` stops the live engine safely and keeps Telegram available.
- `/live_start` can request engine restart while the service remains alive.
- Runtime status writes are locked and atomic inside the single process.
- Existing `telegram-bot` and `live-research` commands remain local fallback commands.

## Files Created

- `src/run_all.py`
- `tests/test_run_all.py`
- `reports/SINGLE_SERVICE_RAILWAY_RUNNER_REPORT.md`
- `reports/SINGLE_SERVICE_RAILWAY_RUNNER_REPORT.json`

## Files Changed

- `src/main.py`
- `src/live_research_engine.py`
- `src/runtime_status.py`
- `README.md`
- `.env.example`
- `deployment/README_DEPLOY.md`
- `deployment/sandbox_live_paper/RUNBOOK.md`
- `deployment/sandbox_live_paper/START_ENGINE.md`
- `deployment/sandbox_live_paper/START_TELEGRAM.md`
- `deployment/sandbox_live_paper/DEPLOY_READINESS_CHECKLIST.md`
- `deployment/sandbox_live_paper/ENV_EXAMPLE.md`
- `tests/test_deployment_docs.py`

## Safety

- Production Crypto13 changed: false
- Real Binance orders: disabled
- Testnet orders: disabled
- Private Binance API: not used
- Telegram Pre-deploy Command: not used

## Scope Correction Results

- Task scope: Single Service Railway Runner only.
- Docker-related files identified: `deployment/docker/Dockerfile`, `export/Crypto13ResearchSandbox/deployment/docker/Dockerfile`.
- Docker-related changes reverted: both Dockerfiles are safe-help default and do not start `run-all`.
- Docker/systemd tracked diff after correction: none.
- Docker deploy not enabled.
- Railway not switched to Docker.
- Systemd files not changed in this correction pass.

## Verification Results

| Command | Result | Exit Code | Summary |
|---|---:|---:|---|
| `./.venv/bin/python -m src.main --help` | PASS | 0 | CLI help rendered and includes run-all command. |
| `./.venv/bin/python -m src.main run-all --help` | PASS | 0 | run-all help rendered and includes --dry-run. |
| `./.venv/bin/python -m src.main run-all --dry-run` | PASS | 0 | Dry-run printed sandbox_run_all, runtime_layout=single_service, production_like_raw, 15m, LONG_ONLY, real/testnet/private API false, Railway Start Command python -m src.main run-all, Pre-deploy empty. |
| `./.venv/bin/python -m pytest -q tests/test_run_all.py tests/test_deployment_docs.py` | PASS | 0 | 11 passed, 1 warning. |
| `./.venv/bin/python -m pytest -q` | PASS | 0 | 115 passed, 1 warning. |
| `cd export/Crypto13ResearchSandbox && ../../.venv/bin/python -m src.main run-all --dry-run` | PASS | 0 | Export dry-run printed sandbox_run_all, runtime_layout=single_service, production_like_raw, 15m, LONG_ONLY, real/testnet/private API false. |
| `cd export/Crypto13ResearchSandbox && ../../.venv/bin/python -m pytest -q` | PASS | 0 | Export full pytest: 115 passed, 1 warning. |

## Full Pytest Result

Main project:

```text
115 passed, 1 warning
```

Export folder:

```text
115 passed, 1 warning
```

## Run-All Dry-Run Result

Main project and export folder both printed:

```text
mode: sandbox_run_all
runtime_layout: single_service
telegram_enabled: True
live_engine_enabled: True
symbols: BTCUSDT, ETHUSDT
timeframe: 15m
candidate_source: production_like_raw
interval_sec: 60
direction: LONG_ONLY
real_orders_enabled: False
testnet_orders_enabled: False
private_api_used: False
railway_start_command: python -m src.main run-all
railway_pre_deploy_command: <empty>
```

## Railway Deployment Settings

Railway Start Command:

```bash
python -m src.main run-all
```

Railway Pre-deploy Command: empty

## Docker Boundary

Docker deploy not enabled. Railway was not switched to Docker. Docker-related accidental runtime change was reverted. `deployment/docker/Dockerfile` remains safe-help default:

```bash
python -m src.main --help
```

## Production Boundary

Production Crypto13 was not touched.
