# Standalone Export Self-Check

Task: 5E-REMAKE Standalone GitHub Sandbox Export Folder

Status: PASS

- [x] `export/Crypto13ResearchSandbox/` exists
- [x] root `README.md` exists
- [x] `.gitignore` exists
- [x] `.env.example` exists
- [x] `src/` included
- [x] `config/` included
- [x] `tests/` included
- [x] deployment docs included under `deployment/sandbox_live_paper/`
- [x] no `.env` included
- [x] no `.git` included
- [x] no `.venv` included
- [x] no `__MACOSX` included
- [x] no `.DS_Store` included
- [x] no real secrets detected by filename/content scan
- [x] no production folder included
- [x] no real/testnet/private API instructions found
- [x] `production_like_raw` documented
- [x] shadow gates documented
- [x] `edge_conclusions_allowed=false` documented
- [x] smoke command documented
- [x] status command documented

## Required Checks

Excluded item check:

```bash
find export/Crypto13ResearchSandbox \( -name ".env" -o -name "__MACOSX" -o -name ".DS_Store" -o -name ".git" -o -name ".venv" \)
```

Result: empty output.

Required file checks:

```bash
test -f export/Crypto13ResearchSandbox/README.md
test -f export/Crypto13ResearchSandbox/.gitignore
test -f export/Crypto13ResearchSandbox/.env.example
test -d export/Crypto13ResearchSandbox/src
test -d export/Crypto13ResearchSandbox/tests
test -d export/Crypto13ResearchSandbox/config
```

Result: passed.

## Test Results

Main project:

```bash
./.venv/bin/python -m pytest -q
```

Result: `105 passed, 1 warning`.

Export folder exact command:

```bash
python -m pytest -q
```

Result: not available in current shell because `python` command is missing.

Export folder verified with installed sandbox venv:

```bash
../../.venv/bin/python -m pytest -q
```

Result: `105 passed, 1 warning`.

The warning is the existing urllib3/LibreSSL environment warning.
