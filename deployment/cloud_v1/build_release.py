"""Allowlisted deterministic source bundle. Never packages runtime data or secrets."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


TESTS = (
    "conftest", "test_cloud_release", "test_strategy_packages",
    "test_multi_strategy_lifecycle", "test_telegram_strategy_lifecycle",
    "test_live_shadow_foundation", "test_telegram_handlers", "test_telegram_bot_export",
    "test_telegram_config", "test_run_all", "test_research_sessions",
    "test_storage_reliability", "test_standard_shadow_execution", "test_legacy_shadow_runtime",
)


def build(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if not destination.is_relative_to(root / "analysis"):
        raise ValueError("build output must be a new analysis subdirectory")
    destination.mkdir(parents=True, exist_ok=False)
    config = root / "deployment/cloud_v1"
    names = (config / "runtime-files.txt").read_text().splitlines()
    names += ["tests/" + name + ".py" for name in TESTS]
    names += ["README.md"] + ["deployment/sandbox_live_paper/" + name for name in (
        "RUNBOOK.md", "START_ENGINE.md", "START_TELEGRAM.md", "DEPLOY_READINESS_CHECKLIST.md")]
    mappings = {name: name for name in names}
    for name in (
        ".python-version",
        "railpack.json",
        "requirements.txt",
        "requirements.lock",
        "requirements-test.lock",
        "runtime-files.txt",
        "build_release.py",
    ):
        mappings[name] = "deployment/cloud_v1/" + name
    mappings["docs/SANDBOX_CLOUD_V1_RELEASE.md"] = "docs/SANDBOX_CLOUD_V1_RELEASE.md"
    hashes = {}
    for name, source in sorted(mappings.items()):
        path = root / source
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("unsafe source path")
        data = path.read_bytes()
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    # A dirty checkout is identified by its content hash, never claimed as HEAD.
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    content = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    manifest = dict(schema=1, base_git_revision=base, revision="source-sha256:" + content,
                    files=hashes, python="3.13.7", platform="linux-x86_64",
                    startup="stopped", runtime_owner="Railway only after cutover",
                    paper_only=True, real_orders=False, testnet_orders=False)
    raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    (destination / "release-manifest.json").write_bytes(raw)
    print(json.dumps(dict(path=str(destination), revision=manifest["revision"],
                         manifest_sha256=hashlib.sha256(raw).hexdigest(), files=len(hashes))))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination")
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[2], args.destination)
