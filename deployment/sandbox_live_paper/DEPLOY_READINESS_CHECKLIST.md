# Deploy Readiness Checklist

This checklist is for a future server deploy decision. It does not deploy anything.

- [ ] Repo clean enough for GitHub
- [ ] Secrets excluded
- [ ] `.gitignore` checked
- [ ] Env example only
- [ ] Railway Start Command set to `python -m src.main run-all`
- [ ] Railway Pre-deploy Command empty
- [ ] Storage paths writable
- [ ] Runtime status writable
- [ ] Command queue writable
- [ ] `python -m src.main run-all --dry-run` passed locally
- [ ] Full tests passed
- [ ] Safety status checked
- [ ] Rollback/stop plan written

## Required Commands To Know

Railway Start Command:

```bash
python -m src.main run-all
```

Pre-deploy Command: empty

Dry-run:

```bash
python -m src.main run-all --dry-run
```

Status:

```bash
./.venv/bin/python -m src.main status
```

Local Telegram fallback only:

```bash
./.venv/bin/python -m src.main telegram-bot
```

## Stop Plan

Use Telegram `/live_stop` first. This should stop the live paper engine, flush paper artifacts, and keep Telegram available. If the Railway service itself must be stopped, stop only the sandbox service and preserve runtime files for review.
