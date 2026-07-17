# HQ Decision Log

Only `Crypto13 HQ` should use this file to record final project decisions.

## Decisions

### 2026-06-02

Decision:

```text
Three-chat structure is the active operating model:
Crypto13 HQ -> Crypto13Research Coder -> Crypto13Research Tester -> Crypto13 HQ.
```

Reason:

```text
Keep strategy, implementation, and validation separate while preserving one shared project context.
```

Status:

```text
ACTIVE
```

### 2026-06-02 - Handoff Protocol Accepted

Decision:

```text
Accept the file-based three-chat handoff protocol.
```

Evidence:

```text
Tester validated PROJECT_CONTEXT.md, docs/CHAT_PROTOCOL.md, README.md, and handoff files.
Tester result: PASSED_WITH_NOTES.
Failed checks: None.
Automated test suite reported by Tester: 21 passed.
Production Crypto13 freshness check reported no modified files.
```

Notes:

```text
Chats still do not communicate automatically through the UI.
The accepted operating model is file-based coordination:
Crypto13 HQ -> Crypto13Research Coder -> Crypto13Research Tester -> Crypto13 HQ.
```

Status:

```text
ACCEPTED
```


### 2026-06-05 - Demo/Paper Research Engine MVP Accepted

Decision:

```text
Accept the Demo/Paper Trading + Hypothesis Engine MVP as the current working sandbox version.
```

Evidence:

```text
Tester status: PASSED_WITH_NOTES.
Tester recommendation: Accept.
Failed checks: None.
Full pytest: 33 passed.
Focused safety/paper/hypothesis/signal tests: 9 passed.
Hypothesis replay generated data/demo_reports/demo_report_20260605_170504.md.
Testnet smoke blocked safely with ALLOW_TESTNET_ORDERS=false.
Production Crypto13 inspection skipped by explicit HQ instruction.
```

Notes:

```text
This acceptance is for Crypto13Research sandbox only.
It is not production approval.
Testnet broker remains blocked/not implemented for actual order placement until explicit HQ approval.
```

Status:

```text
ACCEPTED
```


### 2026-06-05 - Sub-Agent Workflow Activated

Decision:

```text
Switch active operating model from separate Coder/Tester chats to Coder and Tester sub-agents orchestrated by Crypto13 HQ.
```

Reason:

```text
The user should not manually copy tasks between chats. Crypto13 HQ will discuss scope with the user, spawn Coder sub-agent for implementation, spawn Tester sub-agent for validation, and return one final report.
```

Active workflow:

```text
User -> Crypto13 HQ -> Coder sub-agent -> Tester sub-agent -> Crypto13 HQ -> User
```

Notes:

```text
Existing Coder/Tester chats may remain as archive/history, but are no longer the active working loop.
handoffs/ remains as audit trail and fallback file-based protocol.
```

Status:

```text
ACTIVE
```
