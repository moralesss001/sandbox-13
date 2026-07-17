# Documents Duplicate Migration Report

Date: 2026-06-10
Canonical workspace: `/Users/maksimmatveev/Desktop/Crypto13 Research Sandbox/crypto13_research`
Duplicate workspace: `/Users/maksimmatveev/Documents/Crypto13 Research Sandbox`

## Decision

The Desktop project is the only active Crypto13 Research Sandbox workspace.

The Documents project was created/used by mistake because the Codex session was opened with that cwd. It is not the canonical project and must not remain as a second working sandbox.

## What was migrated

The duplicate Documents artifacts were archived into the canonical Desktop project at:

```text
handoffs/documents_migration_archive/
```

Archived content includes:

```text
AGENTS.md
README.md
SANDBOX_READINESS_REPORT.md
TASK_1_TELEGRAM_INBOX_CSV_COMPATIBILITY_REPORT.md
TASK_2_RR_REPLAY_SIMULATOR_REPORT.md
TASK_3_HYPOTHESIS_RUNNER_REPORT.md
bot/
core/
configs/
tests/
reports/
requirements.documents.txt
```

## What was not overwritten

The existing Desktop runtime code was not overwritten:

```text
src/
config/
data/
tests/
deployment/
docs/
handoffs/
```

Reason: Desktop already has an established `src/` architecture and passing tests. The Documents code uses a different `bot/` and `core/` architecture, so blindly copying it over would create conflicts.

## Current journal location

The old journal is already in the canonical Desktop project:

```text
data/journals/signals_export_1897339801.csv
```

## Precheck status

A candle download precheck was produced in the duplicate Documents workspace before this migration. Its copy is now archived at:

```text
handoffs/documents_migration_archive/reports/CANDLE_DOWNLOAD_PRECHECK_REPORT.md
```

The next clean step is to recreate any needed candle precheck/report directly in the canonical Desktop project.

## Verification

Use the Desktop virtual environment:

```bash
cd "/Users/maksimmatveev/Desktop/Crypto13 Research Sandbox/crypto13_research"
./.venv/bin/python -m pytest -q
```

Expected result observed before duplicate deletion:

```text
55 passed
```

## Rule going forward

Do not use `/Users/maksimmatveev/Documents/Crypto13 Research Sandbox` for Crypto13 Research Sandbox work.

All future reads/writes must use:

```text
/Users/maksimmatveev/Desktop/Crypto13 Research Sandbox/crypto13_research
```
