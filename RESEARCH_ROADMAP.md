# Crypto13 Research Roadmap

## Current stage

We are building a demo/paper research engine.

The goal is to test strategy hypotheses without real money.

## Immediate task

Implement:

- Binance public market data integration
- paper broker
- hypothesis runner
- paper portfolios
- live research mode
- testnet foundation
- server-ready foundation

## First mode

Hypothesis Replay Mode.

Command:

```bash
python -m src.main hypothesis-replay --file data/journals/signals_export_1897339801.csv --tf 15m
```

## Second mode

Live Research Paper Mode.

Command:

```bash
python -m src.main live-research --symbols BTCUSDT,ETHUSDT --tf 15m --interval-sec 60
```

## Third mode

Testnet Execution Mode.

Only for 1-2 selected hypotheses.

Disabled by default.

Must require explicit config and explicit CLI confirmation.

## Market data priority

MVP: Use Binance Futures REST polling.

Later: Add Binance Futures WebSocket kline stream.

## Hypotheses to test first

1. baseline_rr15
2. ban_rsi_below_35
3. ban_rsi_below_38
4. ban_rsi_below_40
5. ban_unclear_europe_rebound
6. ban_overlap
7. ban_unclear_low_rsi
8. ban_low_rsi_europe
9. ban_rebound_europe
10. ban_unclear_europe
11. allow_only_mid_rsi
12. allow_only_continuation
13. allow_us_unknown
14. ban_unclear_overlap
15. ban_europe_low_rsi

## Candidate rules

A hypothesis can become candidate for testnet only if:

- total_trades >= 30
- profit_factor > 1.2
- expectancy > 0
- net_R > baseline_net_R
- max_drawdown is acceptable
- result is not based on tiny overfit cluster

## Production rule

Production Crypto13 is separate.
Crypto13Research can recommend.
Only human decision can change production.



## Current HQ Task - VPS 24/7 + Telegram

The accepted MVP must be extended for VPS 24/7 operation.

Primary server mode:

```text
live-research paper mode
```

Required shape:

```text
Binance public REST polling -> closed 15m candles -> signal candidates -> active hypotheses -> separate paper portfolios -> logs/reports/status -> Telegram control panel
```

The research engine and Telegram bot must be separate processes.
Telegram is a read-only/control panel, not a trading executor.

Production trading, real Binance orders, and production Crypto13 access remain forbidden.


## Deployment Target - Railway

Primary deployment path:

```text
GitHub -> Railway
```

Railway should run two separate services from the same repo:

```text
crypto13-live-research
crypto13-telegram-bot
```

Both services must stay paper-only by default.
Secrets must be configured via Railway variables, not committed to git.
If persistent paper logs/reports are required, Railway Volume usage or ephemeral storage limitations must be documented before production-like 24/7 use.
