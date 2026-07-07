# Candidate Source Boundary Report

## 1. Executive Summary

Status: `READY`

Task 5C-B implemented an explicit Candidate Source Boundary / Adapter Interface for Crypto13Research. The current live candidate builder remains the same MA/ATR placeholder logic, but every live candidate now carries stable source metadata.

Current live candidate source:

```text
simplified_placeholder v1
```

This source is explicitly marked as placeholder-only and not valid for edge conclusions.

No production logic was imported. No new entry strategy was added. No RR/TP/SL/risk/leverage/hypothesis behavior was changed.

## 2. What Changed

- Added explicit candidate source types.
- Added candidate source metadata contract.
- Added source metadata fields to `SignalCandidate`.
- Marked current `signal_from_klines()` output as `simplified_placeholder v1`.
- Marked journal/replay candidates as `production_baseline_export legacy_journal_v1` for compatibility/reference metadata.
- Added future stubs for `production_baseline_export` and `new_entry_model_adapter`.
- Added runtime status fields for candidate source and edge warning.
- Preserved live MVP limits: `15m` and `LONG_ONLY`.
- Added safe rejection for unsupported candidate sources.
- Kept SHORT candidates ignored before paper open with reason `short_disabled_live_paper_mvp`.
- Added candidate source warning to generated demo reports and Telegram status text.

## 3. Files Changed

- `src/order_models.py`
- `src/signal_adapter.py`
- `src/live_research_engine.py`
- `src/runtime_status.py`
- `src/telegram_control.py`
- `src/demo_report_builder.py`
- `tests/test_signal_adapter.py`
- `tests/test_live_paper_lifecycle.py`
- `tests/test_runtime_status.py`

## 4. Files Created

- `src/candidate_sources.py`
- `tests/test_candidate_sources.py`
- `tests/test_demo_report_builder.py`
- `reports/CANDIDATE_SOURCE_BOUNDARY_REPORT.md`
- `reports/CANDIDATE_SOURCE_BOUNDARY_REPORT.json`

## 5. Candidate Source Types

Declared in `src/candidate_sources.py`:

```text
simplified_placeholder
production_baseline_export
new_entry_model_adapter
```

Direction support values:

```text
LONG_ONLY
SHORT_ONLY
LONG_AND_SHORT
```

## 6. Candidate Source Metadata Contract

Minimum metadata now exists as stable fields:

- `candidate_source`
- `candidate_source_version`
- `is_placeholder`
- `edge_conclusions_allowed`
- `direction_support`
- `source_description`

These fields were added to `SignalCandidate` and are also exposed through runtime status for the current live source.

Runtime status also keeps `candidate_source_is_placeholder` as an explicit status alias for Telegram/readability, but the base `is_placeholder` contract field is present too.

## 7. Current simplified_placeholder Behavior

Current live builder:

```text
src/signal_adapter.py::signal_from_klines()
```

Metadata:

```text
candidate_source: simplified_placeholder
candidate_source_version: v1
is_placeholder: true
edge_conclusions_allowed: false
direction_support: LONG_AND_SHORT
source_description: MA/ATR simplified placeholder for technical live paper smoke testing only
```

Important: the MA/ATR placeholder logic was not changed.

## 8. Runtime Status Fields

Runtime status now includes:

- `candidate_source`
- `candidate_source_version`
- `is_placeholder`
- `candidate_source_is_placeholder`
- `edge_conclusions_allowed`
- `candidate_source_warning`
- `direction_support`
- `source_description`
- `live_direction_policy`
- `rejected_candidates_count`
- `last_rejected_candidate_reason`

Current warning:

```text
technical smoke source only; do not use for edge conclusions
```

## 9. LONG-only Live MVP Validation

Live runtime remains restricted to:

```text
timeframe: 15m
live_direction_policy: LONG_ONLY
```

The candidate source can emit `LONG_AND_SHORT`, but the live MVP only opens `LONG` candidates.

## 10. SHORT Handling

If the current source emits `SHORT`:

- no paper position is opened;
- `ignored_short_candidates_count` increments;
- `rejected_candidates_count` increments;
- `last_rejected_candidate_reason` becomes `short_disabled_live_paper_mvp`.

## 11. Future production_baseline_export Stub

Stub exists:

```text
src/candidate_sources.py::build_candidate_from_production_baseline_export()
```

It raises `NotImplementedError` and explicitly states that Task 5C-B does not import production files or production code.

## 12. Future new_entry_model_adapter Stub

Stub exists:

```text
src/candidate_sources.py::build_candidate_from_new_entry_model()
```

It raises `NotImplementedError` and explicitly states that Task 5C-B does not implement a new entry strategy.

## 13. Journal / Replay Compatibility

Journal replay remains compatible.

`signals_from_journal()` still creates `SignalCandidate` objects from CSV journal rows, and tests confirm the existing session normalization path still works.

Journal/replay candidates now also receive metadata:

```text
candidate_source: production_baseline_export
candidate_source_version: legacy_journal_v1
is_placeholder: false
edge_conclusions_allowed: true
direction_support: LONG_AND_SHORT
```

This is metadata only; replay logic was not changed.

## 14. What Remains For Task 5C-C

Recommended Task 5C-C scope:

1. Decide whether the next real candidate source should be `production_baseline_export` or `new_entry_model_adapter`.
2. If `production_baseline_export`: implement a safe import format from sandbox-local exports only, without reading production directly.
3. Add schema validation for required candidate columns.
4. Add adapter-level rejection reasons for missing/invalid fields.
5. Keep source metadata mandatory.

## 15. What Remains For Task 5C-D

Recommended Task 5C-D scope:

1. Build or refine the future `new_entry_model_adapter` only after the source boundary is stable.
2. Add proper session/context/HTF fields for live candidates.
3. Add candidate source versioning for model iterations.
4. Keep all edge conclusions disabled until enough prospective paper data exists.

## 16. Risks

- The current `simplified_placeholder` can still create misleading hypothesis outcomes if someone ignores the warning.
- `session=LIVE`, simplified `market_phase`, simplified `setup_type`, and simplified `trend_htf` remain weak fields.
- `production_baseline_export` and `new_entry_model_adapter` are stubs only.
- Research Pack 2 remains inappropriate for live runtime until live candidate fields are reliable.

## 17. Safety Confirmations

- Sandbox only: `true`
- Production code changed: `false`
- Private Binance API used: `false`
- Real orders added: `false`
- Testnet orders added: `false`
- Deploy changed: `false`
- Docker/systemd changed: `false`
- Telegram dashboard changed: `false`
- New hypotheses added: `false`
- Research Pack 2 live enabled: `false`
- Strategy logic changed: `false`

Worktree note: the repository still contains pre-existing uncommitted/untracked artifacts from earlier tasks, including Task 5B lifecycle files and older deployment/hypothesis folders. They were not created or changed by Task 5C-B and are not part of this task's file inventory.

## 18. Test Results

Focused command:

```bash
./.venv/bin/python -m pytest -q tests/test_candidate_sources.py tests/test_signal_adapter.py tests/test_live_paper_lifecycle.py tests/test_runtime_status.py tests/test_live_research_runtime.py tests/test_demo_report_builder.py tests/test_telegram_handlers.py
```

Result:

```text
28 passed, 1 environment warning
```

Full command:

```bash
./.venv/bin/python -m pytest -q
```

Previous result before final report/status metadata clarification:

```text
72 passed, 1 environment warning
```

Final result after clarification patch:

```text
72 passed, 1 environment warning
```

The warning is the existing local urllib3/LibreSSL environment warning and is not a test failure.
