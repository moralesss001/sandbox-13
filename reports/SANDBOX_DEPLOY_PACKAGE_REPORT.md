# Sandbox Deploy Package Report

## Executive Summary

Status: READY

Task 5E created a clean deploy package/runbook for future GitHub preparation and sandbox live paper deployment planning. This task did not deploy, push, add remotes, change production, or enable any trading path.

## Deployment Folder

Created:

```text
deployment/sandbox_live_paper/
```

## Files Created

- `deployment/sandbox_live_paper/README.md`
- `deployment/sandbox_live_paper/RUNBOOK.md`
- `deployment/sandbox_live_paper/ENV_EXAMPLE.md`
- `deployment/sandbox_live_paper/START_ENGINE.md`
- `deployment/sandbox_live_paper/START_TELEGRAM.md`
- `deployment/sandbox_live_paper/SAFETY_CHECKLIST.md`
- `deployment/sandbox_live_paper/FIRST_30_TRADES_PROTOCOL.md`
- `deployment/sandbox_live_paper/TROUBLESHOOTING.md`
- `deployment/sandbox_live_paper/DEPLOY_READINESS_CHECKLIST.md`
- `scripts/sandbox_start_engine.sh`
- `scripts/sandbox_status.sh`
- `scripts/sandbox_stop_note.sh`
- `reports/DEPLOY_PACKAGE_SELF_CHECK.md`
- `reports/SANDBOX_DEPLOY_PACKAGE_REPORT.md`
- `reports/SANDBOX_DEPLOY_PACKAGE_REPORT.json`

## Files Changed

No existing source logic was changed by Task 5E.

## Scripts Created

- `scripts/sandbox_start_engine.sh`: starts sandbox live paper engine using `production_like_raw`.
- `scripts/sandbox_status.sh`: prints sandbox runtime status.
- `scripts/sandbox_stop_note.sh`: prints safe stop guidance.

These scripts do not deploy, push, add remotes, change production, or use secrets.

## Candidate Source

- `candidate_source=production_like_raw`
- `candidate_source_version=v1`
- `timeframe=15m`
- `direction=LONG_ONLY`
- `edge_conclusions_allowed=false`

## Telegram Commands Documented

- `/live_start`
- `/live_stop`
- `/live_status`
- `/source`
- `/open_trades`
- `/closed_trades`
- `/gates`

## CLI Fallback Documented

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
./.venv/bin/python -m src.main status
```

## Safety Confirmations

- Sandbox only: true
- Production code changed: false
- Private Binance API used: false
- Real orders added: false
- Testnet orders added: false
- Deploy performed: false
- Docker/systemd changed: false
- GitHub push performed: false
- Git remote changed: false
- Secrets committed: false
- TP/SL/RR/risk changed: false

## Checks Run

```bash
bash -n scripts/sandbox_start_engine.sh
bash -n scripts/sandbox_status.sh
bash -n scripts/sandbox_stop_note.sh
./.venv/bin/python -m pytest -q
```

Results:

- Shell syntax: passed
- Tests: `105 passed, 1 warning`

## Self-Check

Self-check file created:

```text
reports/DEPLOY_PACKAGE_SELF_CHECK.md
```

Result: PASS

## What This Package Is For

Use it to prepare a future sandbox server run and first 30 closed virtual trades protocol.

## What Remains Before Actual Server Deploy

- Task 5F clean repo review.
- Review `.gitignore`, generated artifacts, data files, and reports before GitHub.
- Decide server process model.
- Configure real Telegram token only outside committed files.
- Verify writable runtime/data paths on server.
- Run local smoke before any server run.

## What Remains Before Edge Conclusions

- Collect first 30 closed virtual trades.
- Prefer 60+ closed virtual trades before strong claims.
- Review gate saved/missed outcomes manually.
- Keep production changes separate and human-approved.
