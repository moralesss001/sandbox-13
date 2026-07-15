from pathlib import Path


def test_railway_docs_mention_github_and_single_service_run_all():
    text = Path("deployment/README_DEPLOY.md").read_text(encoding="utf-8")

    assert "GitHub -> Railway" in text
    assert "separate GitHub repository" in text
    assert "one Railway service" in text
    assert "python -m src.main run-all" in text
    assert "Pre-deploy Command: empty" in text
    assert "Railway Variables" in text
    assert "ephemeral" in text.lower()
    assert "API_MODE=paper" in text
    assert "ALLOW_REAL_ORDERS=false" in text
    assert "ALLOW_TESTNET_ORDERS=false" in text
    assert "Pre-deploy Command: python -m src.main telegram-bot" not in text
