# Troubleshooting

## 1. Telegram Says Queued But Engine Not Running

- Symptom: `/live_start` returns queued, but `/live_status` does not update.
- Likely cause: engine process is not running or is not reading the command queue.
- Safe check: inspect `data/runtime/commands.jsonl` and run `./.venv/bin/python -m src.main status`.
- Safe fix: start the sandbox engine using `START_ENGINE.md`.
- What not to do: do not start or stop production Crypto13.

## 2. `runtime_status.json` Not Updating

- Symptom: status timestamp does not change.
- Likely cause: engine process stopped, wrong working directory, or storage path issue.
- Safe check: verify `data/runtime/runtime_status.json` exists and is writable.
- Safe fix: restart only the sandbox engine from the sandbox folder.
- What not to do: do not edit production runtime files.

## 3. No Candidates For Long Time

- Symptom: `raw_candidates_count` does not increase.
- Likely cause: no new closed 15m candle processed, Binance public data error, or process stopped.
- Safe check: check `/live_status`, `errors`, and latest processed candle time.
- Safe fix: run a one-iteration smoke command from `START_ENGINE.md`.
- What not to do: do not change entry logic to force candidates.

## 4. Binance Public Data Errors

- Symptom: errors mention Binance or HTTP requests.
- Likely cause: network issue, Binance availability, rate limiting, or local DNS issue.
- Safe check: inspect `/live_status` errors and retry a smoke run later.
- Safe fix: keep using public data only; restart sandbox engine if needed.
- What not to do: do not add private Binance API keys.

## 5. Command Queue Stuck

- Symptom: command remains in `data/runtime/commands.jsonl` and control state does not change.
- Likely cause: engine has not processed the queue.
- Safe check: inspect `processed_command_ids` in runtime status.
- Safe fix: restart sandbox engine; keep command queue in sandbox data path.
- What not to do: do not delete runtime files unless you have a backup and explicit reason.

## 6. Open Positions Corrupted Or Missing

- Symptom: `/open_trades` says storage unreadable or no open positions unexpectedly.
- Likely cause: corrupted `data/paper_trades/open_positions.json` or fresh runtime state.
- Safe check: inspect the JSON file format.
- Safe fix: stop sandbox engine, back up the file, then restart sandbox engine.
- What not to do: do not fabricate paper positions.

## 7. `closed_trades.csv` Missing

- Symptom: `/closed_trades` returns no closed paper trades yet.
- Likely cause: no TP/SL closure has occurred or storage is new.
- Safe check: inspect open positions and runtime closed trade count.
- Safe fix: wait for virtual trades to close naturally.
- What not to do: do not manually mark wins/losses.

## 8. `/gates` Shows No Data

- Symptom: gate counts are zero or counters only.
- Likely cause: no closed trades yet or no shadow-blocked candidates yet.
- Safe check: compare `/gates`, `/closed_trades`, and runtime counters.
- Safe fix: continue collecting live paper evidence.
- What not to do: do not make production conclusions from zero/low sample data.

## 9. `edge_conclusions_allowed=false` Warning

- Symptom: Telegram warns that evidence is not production proof.
- Likely cause: this is expected by design.
- Safe check: verify `/source` shows `edge_conclusions_allowed=false`.
- Safe fix: none; continue evidence collection.
- What not to do: do not override the flag to justify production changes.

## 10. Process Stopped Unexpectedly

- Symptom: status stops updating and engine process is gone.
- Likely cause: terminal closed, server restart, Python error, or network exception.
- Safe check: inspect runtime status errors and terminal output.
- Safe fix: restart sandbox engine and Telegram process from the sandbox folder.
- What not to do: do not deploy new infrastructure as part of this troubleshooting package.
