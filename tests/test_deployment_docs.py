from pathlib import Path


def test_railway_docs_mention_github_and_two_services():
    text = Path("deployment/README_DEPLOY.md").read_text(encoding="utf-8")

    assert "GitHub -> Railway" in text
    assert "separate GitHub repository" in text
    assert "crypto13-live-research" in text
    assert "crypto13-telegram-bot" in text
    assert "Railway Variables" in text
    assert "ephemeral" in text.lower()
    assert "API_MODE=paper" in text
