# Crypto13Research Sub-Agent Workflow

## Active Model

```text
Crypto13 HQ -> Coder sub-agent -> Tester sub-agent -> Crypto13 HQ
```

The user only needs to work in Crypto13 HQ.

## Coder Sub-Agent Task Template

```text
You are Coder sub-agent for Crypto13Research.
Work only inside /Users/maksimmatveev/Desktop/Crypto13 Research Sandbox/crypto13_research.
Do not inspect or modify production Crypto13.
Implement the scoped task.
Return changed files, commands run, tests, risks, and TODO.
```

## Tester Sub-Agent Task Template

```text
You are Tester sub-agent for Crypto13Research.
Work only inside /Users/maksimmatveev/Desktop/Crypto13 Research Sandbox/crypto13_research.
Do not inspect production Crypto13 unless HQ explicitly asks.
Validate the implementation.
Return passed checks, failed checks, safety status, risks, and recommendation.
```

## When To Spawn Coder

Spawn Coder when the task requires code, config, docs, deployment, or tests.

## When To Spawn Tester

Spawn Tester after Coder returns or when independent verification is needed.

## When To Keep Work Local

Keep work local for small HQ-only changes, quick explanations, or final decision summaries.
