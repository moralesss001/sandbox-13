# Crypto13Research Sandbox

Crypto13Research Sandbox is a standalone research project for prospective paper/live validation of Crypto13 hypotheses.

This is **not** a production bot. It does not send real orders, does not use Binance private API, and does not modify production Crypto13.

## What It Does

Current live paper flow:

```text
Binance public candles
-> production_like_raw LONG candidates
-> shadow gates
-> hypothesis runner
-> paper trades
-> Telegram control/reporting
```

Current source contract:

- `candidate_source=production_like_raw`
- `candidate_source_version=v1`
- `timeframe=15m`
- `direction=LONG_ONLY`
- `edge_conclusions_allowed=false`

## Safety Rules

- Public Binance candles only.
- Real orders are forbidden.
- Testnet orders are forbidden for this sandbox export.
- Binance private API is forbidden.
- Production Crypto13 is not included and must not be touched.
- No production conclusions before enough paper evidence is collected.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run Tests

```bash
python -m pytest -q
```

## Smoke Test Live Paper

```bash
python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
```

## Runtime Status

```bash
python -m src.main status
```

## Run Live Paper Engine

```bash
python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --run-forever --interval-sec 60
```

## Run Telegram Control

Configure environment variables from `.env.example`, then run:

```bash
python -m src.main telegram-bot
```

Telegram commands:

- `/live_start`
- `/live_stop`
- `/live_status`
- `/source`
- `/open_trades`
- `/closed_trades`
- `/gates`

Telegram queues commands through sandbox runtime files. It does not need to spawn the engine itself.

## First 30 Closed Virtual Trades

Goal: collect the first 30 closed virtual trades.

During this stage:

- no production conclusions;
- no production patches;
- no automatic deployment decisions;
- no real money;
- no rule promotion.

Daily checks:

- `/live_status`
- `/source`
- `/open_trades`
- `/closed_trades`
- `/gates`

At 30 closed virtual trades, collect:

- `data/paper_trades/closed_trades.csv`
- `data/runtime/runtime_status.json`
- gate analytics from `/gates`
- source metadata from `/source`
- errors/log notes

## Why `edge_conclusions_allowed=false`

`production_like_raw` is a research source. It is designed to collect prospective evidence, not to prove a production edge immediately. Production decisions require manual review after enough closed virtual trades.

## Deployment Docs

Read:

- `deployment/sandbox_live_paper/RUNBOOK.md`
- `deployment/sandbox_live_paper/SAFETY_CHECKLIST.md`
- `deployment/sandbox_live_paper/FIRST_30_TRADES_PROTOCOL.md`

## Export Manifest

See `EXPORT_MANIFEST.md` for included/excluded files and safety guarantees.
