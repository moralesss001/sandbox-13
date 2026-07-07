# Standalone GitHub Export Report

## Executive Summary

Status: READY

Created a standalone GitHub-ready sandbox export folder:

```text
export/Crypto13ResearchSandbox/
```

This folder can be uploaded into a new GitHub repository as an independent Crypto13Research Sandbox project.

No GitHub push, remote change, server deploy, production change, real/testnet order path, or private API setup was performed.

## Export Folder Structure

```text
export/Crypto13ResearchSandbox/
  README.md
  .gitignore
  .env.example
  EXPORT_MANIFEST.md
  requirements.txt
  pytest.ini
  src/
  config/
  tests/
  reports/
  deployment/
    README_DEPLOY.md
    sandbox_live_paper/
  scripts/
  data/.gitkeep
  data/runtime/.gitkeep
  data/paper_trades/.gitkeep
```

## Included

- Current sandbox source code in `src/`
- Safe sandbox configs in `config/`
- Current tests in `tests/`
- Key readiness/deploy reports in `reports/`
- Sandbox live paper runbook in `deployment/sandbox_live_paper/`
- Safe local scripts in `scripts/`
- `README.md`, `.gitignore`, `.env.example`, `requirements.txt`, `pytest.ini`
- Empty data folders tracked only by `.gitkeep`

## Excluded

- `.env`
- real tokens
- real API keys
- `.git/`
- `.venv/`
- `.pytest_cache/`
- `__pycache__/`
- `.DS_Store`
- `__MACOSX/`
- old zip archives
- production folders
- production runtime data
- journals/candles/runtime outputs
- paper trade CSV/JSON outputs

## Safety

- GitHub push performed: false
- Git remote changed: false
- Deploy performed: false
- Production changed: false
- Secrets included: false
- Real orders enabled: false
- Testnet orders enabled: false
- Private API enabled: false
- Candidate source: `production_like_raw`
- Edge conclusions: `edge_conclusions_allowed=false`

## Commands Documented In Export README

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1
python -m src.main status
python -m src.main telegram-bot
```

## Tests

Main project command:

```bash
./.venv/bin/python -m pytest -q
```

Result: `105 passed, 1 warning`.

Export exact command:

```bash
python -m pytest -q
```

Result: not available in this shell because `python` command is missing.

Export verified command:

```bash
../../.venv/bin/python -m pytest -q
```

Result: `105 passed, 1 warning`.

## Self-Check

Created:

```text
reports/STANDALONE_EXPORT_SELF_CHECK.md
```

Result: PASS.

## How To Use Next

1. Manually create a new GitHub repository.
2. Upload the contents of `export/Crypto13ResearchSandbox/` into that repository.
3. Do not upload parent folders, runtime data, `.venv`, or real `.env` files.
4. Install dependencies and run tests from the new repository.
5. Run the smoke command before any long-running live paper process.
