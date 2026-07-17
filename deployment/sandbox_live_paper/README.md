# Crypto13Research Sandbox Live Paper Package

This package is only for **Crypto13Research Sandbox**.

It is not a production bot, not a trading deployment, and not a GitHub publication step. It prepares the local/server runbook for sandbox live paper research.

## Scope

- Mode: `sandbox_live_paper`
- Candidate source: `production_like_raw`
- Candidate source version: `v1`
- Timeframe: `15m`
- Direction: `LONG_ONLY`
- Edge conclusions: `edge_conclusions_allowed=false`

## Safety Rules

- Uses only Binance public candle data.
- Real orders are forbidden.
- Testnet orders are forbidden for this package.
- Binance private API is forbidden.
- Production Crypto13 is not controlled by this package.
- Telegram controls only sandbox live paper through command queue and status files.
- No production conclusions are allowed from this stage.

## Near-Term Goal

Collect the first 30 closed virtual trades from `production_like_raw` live paper and review evidence manually.

Before 30 closed trades: no production patches, no real money, no automatic deployment decisions, and no rule promotion.

## Main Runtime Files

- `data/runtime/runtime_status.json`
- `data/runtime/commands.jsonl`
- `data/paper_trades/open_positions.json`
- `data/paper_trades/closed_trades.csv`
- `reports/`

## Read Next

1. `RUNBOOK.md`
2. `ENV_EXAMPLE.md`
3. `SAFETY_CHECKLIST.md`
4. `FIRST_30_TRADES_PROTOCOL.md`
