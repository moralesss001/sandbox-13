# HQ Outbox

Use this file when `Crypto13 HQ` sends a task to `Crypto13Research Coder` or `Crypto13Research Tester`.

## Active Task

Status: `FIX_REQUIRED_FOR_CODER`

Target chat:

```text
Crypto13Research Coder
```

Task title:

```text
Fix VPS/Telegram implementation gaps before Tester review.
```

Context:

```text
Coder implemented the VPS/Telegram layer and pytest passes, but HQ review found missing requirements from the latest task.

This is not ready for Tester acceptance yet.
Production Crypto13 is out of scope and must not be inspected or modified.
```

Fix required:

```text
1. Telegram live research control must use buttons, not only text commands.
   Required buttons:
   - Start Live Research
   - Stop Live Research
   - Restart Live Research
   - Live Status
   - Latest Report
   - Safety

2. Implement /start_live.
   /start_live must show a confirmation screen before starting live research.

3. Implement manual Stop Live Research behavior.
   When Stop is pressed:
   - stop live research safely;
   - save current paper portfolios;
   - flush paper trades and hypothesis events to disk;
   - generate final stop report;
   - send report/path to Telegram.

4. Do not auto-stop live research after fixed time by default.
   Safe smoke tests may keep max-iterations=1, but server mode must require explicit --run-forever and run until Stop or service shutdown.

5. Make the control path explicit between Telegram and engine.
   If using data/runtime/commands.jsonl, add safe commands for:
   - START_LIVE_RESEARCH
   - STOP_LIVE_RESEARCH
   - RESTART_LIVE_RESEARCH
   - RUN_HYPOTHESIS_REPLAY
   - GENERATE_PAPER_REPORT
   Trading/order commands must remain rejected.

6. Railway deployment docs are incomplete.
   deployment/README_DEPLOY.md must document GitHub -> Railway deployment as the primary path, including:
   - separate GitHub repo for Crypto13Research;
   - two Railway services: crypto13-live-research and crypto13-telegram-bot;
   - separate start commands;
   - Railway Variables;
   - storage/volume or ephemeral storage limitations;
   - paper-only defaults.

7. Add/update tests for:
   - Telegram buttons exist;
   - /start_live confirmation;
   - unauthorized user cannot press buttons;
   - forbidden trading buttons/commands do not exist;
   - command queue accepts only safe control commands;
   - Stop Live Research creates/requests final stop report behavior;
   - Railway docs mention GitHub -> Railway and two-service setup.
```

What not to do:

```text
- Do not inspect or modify Crypto13-main-4.
- Do not use production .env/API keys.
- Do not send real Binance orders.
- Do not enable testnet orders.
- Do not implement Telegram real/testnet trading commands.
- Do not make strategic decisions outside HQ.
```

What to return to HQ:

```text
- changed files;
- commands run;
- pytest result;
- short explanation of button flow;
- short explanation of Stop Live Research flow;
- Railway deployment notes;
- remaining risks/TODO.
```
