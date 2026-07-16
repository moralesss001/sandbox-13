# Live Paper Data Integrity Audit

## 1. Executive Summary

Status: **READY** for sandbox-only live paper collection after Task 5G.

The reported values `raw_candidates_count=68`, `open_virtual_positions_count=146`, and
`closed_trades_count=678` use different units. A raw candidate is candidate-level, while open and
closed trades are hypothesis-portfolio position instances. The current registry has 15 active
hypotheses, so one raw candidate may legitimately create several virtual positions. The closed
trade file is cumulative; open positions are a current snapshot.

This fan-out and lifetime/current difference explain why open or closed counts can exceed raw
candidates. They do not prove that the Railway data contains duplicates. Exact reconciliation of
the displayed Railway counts is impossible without its runtime files.

The code audit did confirm idempotency defects that could create duplicates after a crash between
trade persistence and the candle checkpoint. It also confirmed that the stop path could replace a
cumulative closed count with a current-process count. Both defects are fixed and regression-tested.

## 2. Scope Confirmation

- Sandbox repository only: `moralesss001/sandbox-13`.
- Production Crypto13 was not read or changed.
- Entry logic, TP, SL, RR, leverage, risk, shadow gates, hypotheses, and filters were not changed.
- No Docker, systemd, Railway deployment, or Railway configuration files were changed.
- No real orders, testnet orders, private Binance API, or private credentials were added.
- GitHub does not expose the temporary filesystem of the running Railway container.
- Current Railway runtime files were not directly inspected.

## 3. Actual Storage Paths

`CRYPTO13_DATA_ROOT` defaults to `data`. Task 5G resolves it once with `Path.resolve()`, so the
runtime root is `<process working directory>/data` unless the environment overrides it.

| Data | Resolved path | Reader | Writer | Parent created |
| --- | --- | --- | --- | --- |
| Runtime status | `<data_root>/runtime/runtime_status.json` | `RuntimeStatusStore.read` | `RuntimeStatusStore.write/update` | Yes |
| Command queue | `<data_root>/runtime/commands.jsonl` | `CommandQueue.read_all` | `CommandQueue.enqueue` | Yes on write |
| Open positions | `<data_root>/paper_trades/open_positions.json` | `LivePaperStorage.load_open_positions` | `LivePaperStorage.save_open_positions` | Yes |
| Closed trades | `<data_root>/paper_trades/closed_trades.csv` | `LivePaperStorage._read_closed_rows` | `LivePaperStorage.append_closed_trades` | Yes |
| Daily paper trades | `<data_root>/paper_trades/paper_trades_YYYYMMDD.csv` | reporting tools | `HypothesisRunner.save_artifacts` | Yes |
| Portfolio snapshots | `<data_root>/paper_portfolios/portfolio_snapshots_YYYYMMDD.csv` | Telegram/reporting | `HypothesisRunner.save_artifacts` | Yes |
| Hypothesis events | `<data_root>/hypothesis_events/hypothesis_events_YYYYMMDD.csv` | Telegram/reporting | `HypothesisRunner.save_artifacts` | Yes |

`/live_status` and `/status` now expose:

- `runtime_data_directory`
- `runtime_status_path`
- `open_positions_path`
- `closed_trades_path`
- `paths_exist`

`run-all` passes the same `data_root` to Telegram, the live engine, and the status store. The former
custom-root split between Telegram and the engine is removed.

The exact current Railway absolute prefix must be read from `/live_status` or `/export_data`; this
audit does not invent a Railway working directory that was not inspected.

## 4. Storage Call Graph

```text
python -m src.main run-all
  -> RunAllConfig.data_root
  -> RuntimeStatusStore(<data_root>/runtime/runtime_status.json)
  -> TelegramControlPanel(data_root=<same data_root>)
  -> LiveResearchEngine(data_root=<same data_root>)
       -> LivePaperStorage
          -> restore_open_positions()
          -> save_open_positions() [atomic replace]
          -> append_closed_trades() [deduplicated atomic rewrite]
          -> closed_trades_count() [CSV record count]
       -> HypothesisRunner
          -> one decision per enabled hypothesis
          -> one paper portfolio per hypothesis
```

## 5. Counter Semantics

| Counter | Meaning | Scope/source | Restart behavior |
| --- | --- | --- | --- |
| `raw_candidates_count` | Backward-compatible alias of raw candidate lifetime count | Persisted status | Preserved while status file exists |
| `raw_candidates_current_run` | Candidate-level signals built by current engine invocation | In memory, checkpointed to status | Resets on engine invocation |
| `raw_candidates_lifetime` | Candidate-level cumulative count | Persisted status | Preserved while status file exists |
| `open_virtual_positions_count` | Current position instances across all hypothesis portfolios | Open positions snapshot | Restored from JSON |
| `open_positions_current` | Explicit alias for current open instances | Open positions snapshot | Restored from JSON |
| `closed_trades_count` | Backward-compatible cumulative CSV record count | Closed CSV | Preserved while CSV exists |
| `closed_trades_lifetime` | Explicit cumulative closed position instances | Closed CSV | Preserved while CSV exists |
| `production_would_allow_count` | Cumulative raw candidates whose shadow production decision allowed | Persisted status | Preserved while status exists |
| `production_would_block_count` | Cumulative raw candidates whose shadow production decision blocked | Persisted status | Preserved while status exists |
| `shadow_blocked_but_tracked_count` | Blocked raw candidates still sent into research portfolios | Persisted status | Preserved while status exists |

### Expected cumulative behavior

- One raw candidate is evaluated by 15 active hypotheses.
- Each allowing hypothesis can own one virtual position for that candidate.
- Therefore open plus closed hypothesis positions can exceed raw candidates by design.
- `closed_trades.csv` is cumulative; `open_positions.json` is current state.

### Confirmed defects

- Closed CSV appends had no stable-ID deduplication.
- Trade IDs were random and could not protect a crash/restart replay.
- The candle checkpoint was persisted after paper trade side effects, leaving a crash window.
- Stop used current-process portfolio closures instead of cumulative CSV closures.
- A custom data root was passed to the engine but not to Telegram.
- Telegram stop/start overwrote `sandbox_run_all` mode metadata.

### Ambiguous or inconclusive

- The audit cannot prove whether the existing Railway rows contain duplicates because those files
  were not available from GitHub.
- Legacy positions/trades created before Task 5G have no stable `signal_id`; they cannot be fully
  retroactively matched without exporting the actual files.
- Exact arithmetic for 68/146/678 needs the exported event/open/closed files because the counters
  may span different process lifetimes.

## 6. Duplicate Audit

Before Task 5G, `new_trade_id` used a UUID and no `candidate_id`/`signal_id` existed in live paper
positions. Normal polling skipped the last processed candle, but a crash after a trade write and
before the status checkpoint could replay that candle.

Task 5G adds:

- deterministic candidate identity from candidate source/version, symbol, timeframe, direction,
  candle time, and setup type;
- deterministic hypothesis-level `signal_id` from candidate ID plus hypothesis ID;
- rejection of an already-open signal in the same portfolio;
- rejection of an already-closed signal restored from closed CSV;
- closed CSV reconciliation before restoring open positions, so a stale open snapshot cannot
  resurrect a signal already recorded as closed;
- deduplication while restoring open positions;
- deduplication before persisting closed trades;
- CSV-record counting through `csv.DictReader` instead of physical line counting;
- stable IDs in hypothesis events, positions, and closed trades.

The multi-portfolio design remains unchanged: one candidate may produce one distinct signal per
hypothesis, but the same candidate/hypothesis pair cannot be opened or closed twice.

## 7. Confirmed Root Causes

1. The apparent counter mismatch is primarily a semantic mismatch: candidate-level count versus
   hypothesis-position counts, combined with current versus lifetime scopes.
2. The stop path used current-run closed portfolios and could corrupt the displayed cumulative
   count.
3. Missing stable IDs and append deduplication created a real crash/restart duplicate risk.
4. Runtime files are inside the service filesystem, not tracked by GitHub. Only `.gitkeep` files are
   committed under runtime data folders.
5. Without a Railway Volume, runtime files are not durable across container replacement/redeploy.

## 8. Fixes Applied

- Canonical absolute runtime data root shared by Telegram and engine.
- Absolute path diagnostics and existence flags in runtime status.
- Atomic open-position snapshot writes.
- Stable candidate and hypothesis signal IDs.
- Open, restore, and closed persistence deduplication.
- Correct CSV record count and schema-safe atomic rewrite.
- Current-run/lifetime counter clarification with backward-compatible fields.
- Cumulative closed count preserved on stop.
- `sandbox_run_all` and `single_service` metadata preserved on start/stop/restart.
- Telegram error persistence stores exception class only, not token-bearing request URLs.
- Authorized `/export_data` command and `Export data` button.

## 9. Telegram Export Behavior

Use `/export_data` or press **Export data**.

The bot sends only these allowlisted documents when present:

1. sanitized `runtime_status.json` snapshot;
2. `open_positions.json`;
3. `closed_trades.csv`;
4. generated `run_summary.json`.

Every attachment is generated as a sanitized export copy. JSON and CSV values redact secret-like
keys and Telegram-token URL patterns. `.env`, command queue, project files, system files, tokens,
and credentials are never included. Missing files do not abort the export; Telegram reports each
expected absolute path and sends the remaining files.

Both the Telegram user ID and destination chat ID are checked. `TELEGRAM_ALLOWED_CHAT_ID` is used
when set; otherwise the allowed user ID is also the allowed private chat ID.

## 10. Stop/Start Behavior

- `/live_start` still requires confirmation.
- A running or start-requested engine does not queue another start command.
- `run-all` owns one engine supervisor thread; Telegram start changes state and does not create a
  second worker.
- `/live_stop` queues a safe stop; the engine flushes open positions and daily artifacts.
- The supervisor leaves Telegram alive while engine state is stopped.
- The stopped state prevents new engine iterations until a manual start/restart request.
- Stop preserves `mode=sandbox_run_all` and `runtime_layout=single_service`.

## 11. Persistence Limitations

- Process restart with the same filesystem: status, open positions, closed IDs, and candle
  checkpoints can be restored.
- Railway redeploy/container replacement without a Volume: runtime files can be lost.
- GitHub never contains the current Railway runtime filesystem.
- No Railway Volume or deploy configuration was added in Task 5G.
- Future persistent setup should mount a Railway Volume at `/data` and set
  `CRYPTO13_DATA_ROOT=/data`. This is a recommendation only, not an applied deploy change.

## 12. Files Changed

- `src/hypothesis_runner.py`
- `src/live_paper_storage.py`
- `src/live_research_engine.py`
- `src/order_models.py`
- `src/paper_broker.py`
- `src/portfolio.py`
- `src/run_all.py`
- `src/runtime_status.py`
- `src/telegram_bot.py`
- `src/telegram_buttons.py`
- `src/telegram_config.py`
- `src/telegram_control.py`
- `src/telegram_handlers.py`
- `src/telegram_live_paper.py`
- `tests/test_live_paper_lifecycle.py`
- `tests/test_run_all.py`
- `tests/test_telegram_config.py`
- `tests/test_telegram_handlers.py`

## 13. Files Created

- `src/telegram_export.py`
- `tests/test_live_paper_data_integrity.py`
- `tests/test_telegram_bot_export.py`
- `reports/LIVE_PAPER_DATA_INTEGRITY_AUDIT.md`
- `reports/LIVE_PAPER_DATA_INTEGRITY_AUDIT.json`

## 14. Verification Results

All commands were executed in the Task 5G checkout. The existing project virtual environment was
used by absolute path.

| Actual command | Exit | Result |
| --- | ---: | --- |
| `.../.venv/bin/python -m src.main --help` | 0 | CLI help printed; `run-all`, `telegram-bot`, and `live-research` present |
| `.../.venv/bin/python -m src.main run-all --dry-run` | 0 | `sandbox_run_all`, `single_service`, paper-only safety, start command correct |
| `.../.venv/bin/python -m pytest -q tests/test_run_all.py` | 0 | 11 passed, 0 failed, 1 environment warning |
| `.../.venv/bin/python -m pytest -q` | 0 | 132 passed, 0 failed, 1 environment warning |

Independent tester result after two correction rounds: **READY**, no remaining findings; focused
integrity suite: 15 passed, 0 failed.

The warning is the pre-existing urllib3/LibreSSL compatibility warning from the local Python
environment. It is not a Task 5G test failure.

## 15. Remaining Risks

- Existing Railway runtime rows were not inspected; use `/export_data` after deployment to audit
  their actual IDs and duplicates.
- Legacy rows without `signal_id` retain best-effort `trade_id` handling and cannot receive perfect
  retroactive candidate identity.
- File locks are process-local. Task 5F uses one process/service, but multiple independent service
  replicas writing the same Volume would require a stronger storage backend or inter-process lock.
- Persistence remains ephemeral until a Railway Volume is deliberately configured in a later task.

## 16. Safety Confirmations

- Production changed: **false**
- Docker changed: **false**
- Systemd changed: **false**
- Railway config changed: **false**
- Real orders enabled/added: **false**
- Testnet orders enabled/added: **false**
- Private Binance API used/added: **false**
- Strategy, TP, SL, RR, leverage, risk, gates, hypotheses changed: **false**
