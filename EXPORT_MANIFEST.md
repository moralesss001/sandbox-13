# Export Manifest

Export folder:

```text
export/Crypto13ResearchSandbox/
```

## Included

- `README.md`
- `.gitignore`
- `.env.example`
- `requirements.txt`
- `pytest.ini`
- `src/`
- `config/`
- `tests/`
- `reports/` with key readiness, deploy-package, and single-service Railway runner reports
- `deployment/sandbox_live_paper/`
- `scripts/` with safe sandbox scripts only
- `data/.gitkeep`
- `data/runtime/.gitkeep`
- `data/paper_trades/.gitkeep`
- project context docs: `AGENTS.md`, `PROJECT_CONTEXT.md`, `RESEARCH_ROADMAP.md`

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
- private journals and candles
- runtime JSON/JSONL files
- paper trade CSV/JSON outputs

## Safety Guarantees

- GitHub push performed: false
- Git remote changed: false
- Deploy performed: false
- Production changed: false
- Secrets included: false
- Real orders enabled: false
- Testnet orders enabled: false
- Private API enabled: false

## Entrypoints

- CLI entrypoint: `python -m src.main`
- Railway Start Command: `python -m src.main run-all`
- Railway Pre-deploy Command: empty
- Dry-run command: `python -m src.main run-all --dry-run`
- Smoke command: `python -m src.main live-research --symbols BTCUSDT --tf 15m --candidate-source production_like_raw --max-iterations 1`
- Status command: `python -m src.main status`
- Telegram fallback command: `python -m src.main telegram-bot`

## Current Research Source

- `candidate_source=production_like_raw`
- `timeframe=15m`
- `direction=LONG_ONLY`
- `edge_conclusions_allowed=false`

## Tests Run

Main project command:

```bash
./.venv/bin/python -m pytest -q
```

Export folder command:

```bash
python -m pytest -q
```

Results are recorded in `reports/STANDALONE_GITHUB_EXPORT_REPORT.md` in the source project.
