# First 30 Closed Virtual Trades Protocol

## Goal

Collect the first 30 closed virtual trades from sandbox live paper using `production_like_raw`.

## During First 30 Closed Trades

- No production conclusions.
- No production patches.
- No automatic deployment decisions.
- No real money.
- No rule promotion.
- No Research Pack 2 live activation.

## Daily Check

- `/live_status`
- `/source`
- `/open_trades`
- `/closed_trades`
- `/gates`

## At 30 Closed Trades Collect

- `data/paper_trades/closed_trades.csv`
- `data/runtime/runtime_status.json`
- Gate analytics from `/gates`
- Source metadata from `/source`
- Errors/log notes from status and runtime files

## Metrics For First Review

- `closed_trades_count`
- TP count
- SL count
- `net_R`
- Profit factor
- `expectancy_R`
- Max drawdown if available
- `gate_saved_from_loss`
- `gate_missed_profit`
- `gate_allowed_loss`
- `gate_allowed_profit`
- `shadow_blocked_but_tracked_count`
- `production_would_allow_count`
- `production_would_block_count`

## Review Rule

At 30 closed trades, review evidence only. Do not promote a rule to production. Stronger claims require a larger prospective sample.
