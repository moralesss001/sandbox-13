# Deploy Readiness Checklist

This checklist is for a future server deploy decision. It does not deploy anything.

- [ ] Repo clean enough for GitHub
- [ ] Secrets excluded
- [ ] `.gitignore` checked
- [ ] Env example only
- [ ] Sandbox engine command known
- [ ] Telegram command known
- [ ] Storage paths writable
- [ ] Runtime status writable
- [ ] Command queue writable
- [ ] Smoke run passed locally
- [ ] Full tests passed
- [ ] Safety status checked
- [ ] Rollback/stop plan written

## Required Commands To Know

Engine smoke:

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
```

Status:

```bash
./.venv/bin/python -m src.main status
```

Telegram:

```bash
./.venv/bin/python -m src.main telegram-bot
```

## Stop Plan

Use Telegram `/live_stop` first. If the sandbox process itself must be stopped, stop only the sandbox process and preserve runtime files for review.
