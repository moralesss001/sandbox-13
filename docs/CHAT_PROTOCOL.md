# Sub-Agent Workflow Protocol

This project now uses one active user-facing chat:

```text
Crypto13 HQ
```

Coder and Tester are sub-agent roles spawned and managed by Crypto13 HQ.
They are not active standalone working chats by default.

## Workflow

```text
User -> Crypto13 HQ -> Coder sub-agent -> Tester sub-agent -> Crypto13 HQ -> User
```

1. User discusses a task in Crypto13 HQ.
2. HQ defines scope, safety rules, and acceptance criteria.
3. HQ spawns a Coder sub-agent for implementation when needed.
4. Coder sub-agent changes files in Crypto13Research only and reports back.
5. HQ reviews implementation and spawns a Tester sub-agent.
6. Tester sub-agent validates tests, CLI, reports, and safety.
7. If Tester finds issues, HQ returns the fix list to Coder sub-agent.
8. HQ gives the user the final summary and records important decisions.

## Role Boundaries

### Crypto13 HQ

- Owns project decisions.
- Owns final acceptance.
- Orchestrates sub-agents.
- Talks to the user.

### Coder Sub-Agent

- Implements scoped code tasks.
- Does not make strategy decisions.
- Does not touch production Crypto13.

### Tester Sub-Agent

- Validates scoped implementation.
- Reports pass/fail and risks.
- Does not approve production changes.

## Project Files

`PROJECT_CONTEXT.md` is the single source of truth for roles, safety rules, and project boundaries.

`handoffs/` is retained as an audit trail and fallback file-based workflow:

- `handoffs/HQ_OUTBOX.md`
- `handoffs/CODER_REPORT.md`
- `handoffs/TESTER_REPORT.md`
- `handoffs/DECISION_LOG.md`

Sub-agents may update these files when HQ asks, but normal operation is orchestrated directly from Crypto13 HQ.

## Safety Rule

No sub-agent may assume production access. Crypto13Research work stays inside:

```text
/Users/maksimmatveev/Desktop/Crypto13 Research Sandbox/crypto13_research
```

Production Crypto13 is out of scope unless the user explicitly gives a separate command.
