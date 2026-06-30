# Crypto13 Project Context

## Main project

Crypto13 is a crypto futures trading signal bot.

The production bot already exists separately.

Crypto13Research is not a replacement for production Crypto13.

Crypto13Research is a sandbox for:

- journal replay
- hypothesis testing
- paper trading
- demo/testnet validation
- adaptive architecture research
- market phase/session/setup/HTF analysis

## Current production status

Production Crypto13 is currently focused on:

- timeframe: 15m
- direction: LONG
- RR: 1.5
- target sample: 60+ closed trades
- production changes only after human review
- no random changes to strategy

## Latest RR 1.5 research report

Latest journal analyzed:

- closed trades: 98
- wins: 34
- losses: 64
- winrate: 34.69%
- profit factor: 0.80
- expectancy: -0.13R
- net_R: -12.98R

Conclusion: Current 15m RR 1.5 logic is negative without additional filtering.

## Strongest findings

### 1. RSI < 35

LOW RSI:

- trades: 27
- wins: 3
- losses: 24
- winrate: 11.11%
- net_R: -19.53R

This is currently the strongest filter candidate.

### 2. Main toxic cluster

unclear + EUROPE + rebound:

- trades: 17
- wins: 2
- losses: 15
- winrate: 11.76%
- net_R: -11.94R
- confidence: HIGH

### 3. OVERLAP session

OVERLAP:

- trades: 8
- wins: 0
- losses: 8
- winrate: 0%
- net_R: -8R

### 4. US session

US session in the latest RR 1.5 sample:

- trades: 51
- wins: 25
- losses: 26
- winrate: 49.02%
- net_R: +11.48R

Important: Do not use the old assumption "US is bad". Session behavior changed between samples.

### 5. EUROPE session

EUROPE:

- trades: 25
- wins: 4
- losses: 21
- winrate: 16%
- net_R: -14.96R

EUROPE was the worst session in the latest RR 1.5 sample.

### 6. Rebound setup

rebound:

- trades: 67
- wins: 21
- losses: 46
- winrate: 31.34%
- net_R: -14.47R

Rebound is currently weak, especially in EUROPE and OVERLAP.

### 7. Continuation setup

continuation:

- trades: 4
- wins: 4
- losses: 0
- winrate: 100%
- net_R: +5.99R

Promising but sample is too small.

### 8. HTF alignment

countertrend:

- trades: 85
- winrate: 34.12%
- net_R: -12.48R

aligned:

- trades: 13
- winrate: 38.46%
- net_R: -0.50R

HTF alignment alone is not enough as a filter. It may be useful only as secondary context.

## Current hypothesis priority

Priority 1: ban_rsi_below_35
Priority 2: ban_unclear_europe_rebound
Priority 3: ban_overlap
Priority 4: ban_rebound_europe
Priority 5: ban_unclear_europe
Priority 6: allow_only_continuation, but sample is too small
Priority 7: allow_us_unknown

## What NOT to do

Do not:

- create a new unrelated strategy
- invent new indicators before testing existing hypotheses
- optimize on tiny samples
- auto-deploy best hypothesis
- modify production Crypto13
- use production API keys
- place real production orders
- treat paper results as final proof
- confuse paper/testnet results with production results

## Correct research process

1. Replay existing journal.
2. Test hypotheses on journal.
3. Run paper trading live.
4. Compare hypotheses.
5. Select candidates.
6. Validate candidates on testnet/demo.
7. Human review.
8. Only then consider production changes.

## Sandbox coordination context

Crypto13Research is a sandbox/research project for Crypto13.

It is not the production trading bot.
It does not trade real money.
It does not change production Crypto13.

## Active Operating Model

Crypto13 HQ is the only active user-facing project chat.

Coder and Tester are sub-agent roles orchestrated from Crypto13 HQ.
They are not active standalone working chats by default.

### Crypto13 HQ

Main project chat and orchestrator.

Responsibilities:
- discuss tasks with the user;
- make decisions;
- define scope and safety boundaries;
- spawn Coder sub-agent when implementation is needed;
- spawn Tester sub-agent when validation is needed;
- review sub-agent results;
- decide what is accepted, blocked, or returned for fixes.

### Coder Sub-Agent

Temporary implementation agent spawned by Crypto13 HQ for a specific task.

Responsibilities:
- write code;
- modify files inside Crypto13Research only;
- implement the scoped task from HQ;
- run implementation-level checks when requested;
- return changed files, commands, results, risks, and TODO.

Coder sub-agent must not:
- inspect or modify production Crypto13;
- make strategic decisions;
- enable real/testnet trading without explicit HQ approval.

### Tester Sub-Agent

Temporary validation agent spawned by Crypto13 HQ after implementation.

Responsibilities:
- run pytest and smoke tests;
- verify CLI commands;
- verify reports;
- verify safety flags;
- verify that real orders are impossible;
- return pass/fail findings, risks, and recommendation.

Tester sub-agent must not:
- approve production changes;
- inspect production Crypto13 unless HQ explicitly asks;
- alter implementation except for isolated test fixtures if scoped.

## Safety Rules

- Do not use production API keys.
- Do not send real orders.
- Do not write to production DB.
- Do not modify production Crypto13.
- Do not enable testnet/demo/live trading without explicit HQ approval.
- If there is no report, there is no decision.
- If there is no HQ decision, nothing is promoted.

## Current Working Loop

```text
User -> Crypto13 HQ -> Coder sub-agent -> Tester sub-agent -> Crypto13 HQ -> User
```

`handoffs/` remains as audit trail and fallback, but the normal workflow is now orchestrated directly from Crypto13 HQ through sub-agents.
