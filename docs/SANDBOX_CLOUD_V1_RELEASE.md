# Sandbox Cloud V1 release

## Boundary

Candidate for isolated Railway staging, NOT approved for live deployment.
Railway is the only package runtime-owner after explicit cutover. No cross-host
lease exists. Do not run the same package locally after cutover. Existing legacy
observation and its timer are not imported, stopped, or altered by this release.

No strategy, fill model, sizing, fee/funding rule or deadline rule is changed.
Cloud mode bypasses the old research supervisor and its stored commands entirely.
Cloud Telegram exposes only the existing authorized package commands/documents.
New source hashes require newly validated/approved packages, not rewritten old snapshots.

## Build

Run from the authoritative repository:

```sh
python -B deployment/cloud_v1/build_release.py analysis/cloud_v1_candidate
```

Only runtime-files.txt, the explicit test list in build_release.py, locks, Python
version and this document are copied. No .git, credentials, runtime databases,
historical datasets, PID timer, archives or local environment enter the bundle.
release-manifest.json records SHA256 of every copied file. revision is the digest
of the source map; base_git_revision is provenance, not a claim that dirty files
are committed. Build twice into new directories and compare manifests.

## Proposed environment (not applied)

- Python 3.13.7, ordinary CPython, Linux x86_64/glibc >=2.28.
- CRYPTO13_CLOUD_V1=1 (mandatory; without this flag legacy behavior remains).
- CRYPTO13_DATA_ROOT=/app/data; real writable mount required, not a directory.
- CRYPTO13_RELEASE_SHA256= independently retained SHA256 of release-manifest.json.
- API_MODE=paper; ALLOW_REAL_ORDERS=false; ALLOW_TESTNET_ORDERS=false;
  PRODUCTION_TRADING_ENABLED=false.
- Start: python -m src.main run-all. Pre-deploy empty. One replica/receiver.
- Install: python -m pip install --require-hashes -r requirements.lock.
- Tests: python -m pip install --require-hashes -r requirements-test.lock.
- Keep Telegram token absent in staging. Do not poll Telegram in staging.

Locks contain all resolved dependencies and wheel SHA256, targeted to cp313 Linux
x86_64, not macOS/arm64. Download/hash resolution is not proof of Linux execution.

## Storage and startup

Persistent namespace: /app/data/cloud_packages_v1. Do not copy any old DB into it.
New package, lifecycle and shadow DBs have user_version=1. Unsupported versions,
cloud unversioned existing tables, wrong required tables/columns are rejected
before DDL. Local version-0 journals are not migrated/stamped on reopening.
SQLite owns crash recovery; never delete its journal files to force startup.

Every process starts with an empty in-memory admission set. Previous queued,
running or paused sessions are startup_held and have no worker until a fresh
authorized /strategy_run ID VERSION passes integrity/approval/deadline checks.
Terminal records remain terminal; expired records cannot run. Original state and
positions are retained, not relabeled as successful trades or silently erased.
Newly queued packages in this process can run. Pre-start Telegram messages are
discarded, not replayed as new authorization. Approval alone never starts a package.
No old global research status/queue is read; use /strategies and /strategy_status.
Lifecycle deadline and entry guards remain authoritative, with no external timer.

Receiver flock covers the one persistent namespace and is held for polling plus
worker cleanup. Initialization failure is fatal in cloud, not a fallback poller.
This is deliberately not a lock across hosts/volumes; cutover must stop the old
Sandbox receiver before configuring the cloud receiver. Do not touch legacy run.
Stale quotes/gaps continue to block entries under the existing foundation rules.

## Validation gate

Local tests: the 13 modules copied by the builder (plus conftest), temporary DBs
only. Includes manifest tampering, no-Git snapshot, receiver contention, missing
mount, incompatible schemas without byte changes, queued restart held until an
explicit request, deduplication, expiry, disabled old controls, plus existing
package/session/storage/execution regressions. No public live strategy starts.

Next isolated Railway staging must record actual Python/Linux/SQLite versions;
install locks with --require-hashes and pip check; verify manifest; run pytest
over the copied tests; test missing mount failure and a NEW disposable volume at
/app/data. No existing Sandbox volume or token. Verify fresh stopped startup and
restart via synthetic tests, not real strategy activation. A real Telegram
receiver/credentials test is a later separately authorized cutover step.
Do not report Linux, physical mount, real transport or resource measurements as
validated from local mocks. Any failure blocks live deployment.

## Backup and rollback

Before a later cutover: consistent SQLite backup plus accepted snapshots and
manifest to separate storage, with SHA256 and restore test. Do not copy a whole
volume inside itself. Never overwrite accumulated data with an older backup.
Keep exact compatible source/schema/dependency bundle. Stop only newly deployed
package workers cooperatively before rollback; preserve unresolved positions and
their journals. Do not resume expired packages, old queues or old global sessions.
An incompatible schema/build must fail closed, not auto-migrate. A rollback to
the pre-package GitHub revision is not a compatible recovery of cloud packages.

## Changes

2026-09-29: source provenance, cloud-only startup and receiver ownership,
non-migrating SQLite schema checks, allowlisted build and hash-locked dependencies.
Rollback local code only against analysis/cloud_v1_prechange, preserving unrelated
pre-existing changes; never restore/delete runtime data as a code rollback.
