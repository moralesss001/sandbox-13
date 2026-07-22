# Sandbox Live Paper Runbook

## What Runs

Railway should run one sandbox service. The single service starts both components inside one Python process:

1. Telegram bot/control loop.
2. Live paper engine using `production_like_raw`.

Railway Start Command:

```bash
python -m src.main run-all
```

Pre-deploy Command: empty

Do not use `python -m src.main telegram-bot` as a Railway Pre-deploy Command. Telegram must run in the service runtime so it stays alive after `/live_stop`.

Separate `telegram-bot` and `live-research` commands remain available only as local fallback commands.

## Start Order

1. Check environment values using `ENV_EXAMPLE.md`.
2. Set Railway Start Command to `python -m src.main run-all`.
3. Leave Railway Pre-deploy Command empty.
4. Deploy the service.
5. In Telegram, check `/live_status`.
6. In Telegram, check `/source`.
7. In Telegram, check `/gates`.

## Runtime Paths

- Global service/lifetime status: `data/runtime/global_runtime_status.json`
- Command queue: `data/runtime/commands.jsonl`
- Session index: `data/sessions/index.json`
- Session manifest: `data/sessions/<session_id>/manifest.json`
- Immutable config snapshot: `data/sessions/<session_id>/config_snapshot.json`
- Session runtime status: `data/sessions/<session_id>/runtime_status.json`
- Open virtual positions: `data/sessions/<session_id>/paper_trades/open_positions.json`
- Closed paper trades: `data/sessions/<session_id>/paper_trades/closed_trades.csv`
- Session events: `data/sessions/<session_id>/events/`
- Session reports: `data/sessions/<session_id>/reports/`

Legacy root runtime and paper files are reference-only `legacy_session_unscoped` data. Do not move, rewrite, or use them as the active session.

## CLI Fallback Commands

Railway dry-run plan:

```bash
python -m src.main run-all --dry-run
```

Safe one-iteration engine smoke:

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
```

Runtime status:

```bash
./.venv/bin/python -m src.main status
```

Telegram fallback:

```bash
./.venv/bin/python -m src.main telegram-bot
```

## Telegram Commands

- `/live_start`
- `/live_stop`
- `/live_status`
- `/source`
- `/open_trades`
- `/closed_trades`
- `/gates`

## Operating Notes

- `run-all` is the primary Railway runtime.
- `run-all` writes `mode=sandbox_run_all` and `runtime_layout=single_service` to runtime status.
- Every confirmed Start after `stopped` creates a new isolated `session_id`.
- The first observed closed candle is the new session checkpoint baseline; the first later closed candle is processed.
- `Stop Live Research` finishes the active iteration, marks remaining positions unresolved, flushes session artifacts, and leaves Telegram available.
- Use `/export_data <session_id>` to export one selected session. Without an ID, Export uses active then last completed.
- Do not touch production Crypto13 processes.
