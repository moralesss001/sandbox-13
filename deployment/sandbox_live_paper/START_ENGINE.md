# Start Sandbox Live Paper Engine

The engine is a separate sandbox process. It reads public Binance candles, creates `production_like_raw` LONG candidates, evaluates hypotheses in paper mode, persists virtual trades, and reads the command queue.

## Long-Running Sandbox Engine

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --run-forever --interval-sec 60
```

## Safe Smoke Run

```bash
./.venv/bin/python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
```

## Important

- Engine process is sandbox-only.
- Engine reads `data/runtime/commands.jsonl`.
- Telegram may queue start/stop commands but does not need to spawn the engine.
- Production processes must not be touched.
- Candidate source must stay `production_like_raw`.
- Timeframe must stay `15m`.
- Direction policy must stay `LONG_ONLY`.
- `edge_conclusions_allowed=false`.
