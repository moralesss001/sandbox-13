# Crypto13 Agent Instructions

## Workspace Boundary

### Primary writable workspace

The primary writable workspace is:

`/Users/maksimmatveev/Desktop/Crypto13 Research Sandbox/crypto13_research`

Inside the primary workspace, agents may:

- read files;
- create files;
- modify files;
- add local skills;
- write sandbox or research code;
- write documentation;
- perform analysis;
- save analysis outputs.

All file changes must stay inside this directory unless the user gives explicit approval in the current task.

---

### Production read-only reference

The production reference project is:

`/Users/maksimmatveev/Desktop/Crypto13-main-4`

`Crypto13-main-4` is read-only reference material.

Inside `Crypto13-main-4`, agents may:

- read files;
- search code;
- analyze structure;
- compare logic;
- understand production behavior;
- use production logic as reference for sandbox design.

Inside `Crypto13-main-4`, agents must not:

- modify files;
- create files;
- delete files;
- format files;
- run autofixes;
- change configs;
- change `.env`;
- change trading logic;
- change risk management;
- change deployment;
- make git commits;
- run git checkout;
- run git reset;
- run git clean.

Reading `Crypto13-main-4` for analysis is allowed.  
Changing `Crypto13-main-4` is forbidden unless the user gives separate explicit approval in the current task.

---

## Default Rule

Write only inside:

`/Users/maksimmatveev/Desktop/Crypto13 Research Sandbox/crypto13_research`

Read from:

`/Users/maksimmatveev/Desktop/Crypto13-main-4`

only when needed for analysis, comparison, or production behavior mapping.

If it is unclear whether a file belongs to sandbox or production, stop and ask.

If a task requires changing `Crypto13-main-4`, stop and request separate explicit confirmation.

---

## Local Skills

Use the local skill:

`.skills/crypto13-change-guardian/SKILL.md`

as the change guard for Crypto13 work.

Apply `crypto13-change-guardian` before:

- editing files;
- creating files;
- proposing code changes;
- changing sandbox logic;
- changing journal logic;
- changing rejected-trade logic;
- changing Telegram logic;
- changing exchange API logic;
- changing deployment-related files;
- changing anything related to strategy, filters, TP, SL, RR, risk, or market mode.

The skill is especially mandatory when a task involves:

- production behavior;
- trading logic;
- risk management;
- secrets;
- `.env`;
- API keys;
- Telegram tokens;
- exchange credentials;
- journal integrity;
- rejected trade logging.

If a requested task could affect production behavior, trading logic, risk management, secrets, `.env`, API keys, Telegram tokens, or exchange credentials, stop and ask for explicit approval before editing.

---

## Execution Discipline

Before making changes, agents must provide:

1. task interpretation;
2. affected files;
3. risk level;
4. validation plan;
5. rollback plan.

Then wait for user confirmation.

After making changes, agents must provide:

1. files changed;
2. diff summary;
3. risk assessment;
4. validation result;
5. next step.
