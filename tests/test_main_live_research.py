from pathlib import Path

import src.main as main_module


def test_direct_live_research_uses_environment_data_root(monkeypatch, tmp_path):
    captured = {}

    class FakeEngine:
        def __init__(self, _config, data_root):
            captured["data_root"] = Path(data_root)

        def run(self, **_kwargs):
            return {"signal_source": "production_like_raw_live"}

        def mark_latest_report(self, report_path):
            captured["latest_report"] = Path(report_path)

    def fake_report(_result, out_dir, **_kwargs):
        captured["report_out"] = Path(out_dir)
        return Path(out_dir) / "report.md"

    monkeypatch.setenv("CRYPTO13_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(main_module, "LiveResearchEngine", FakeEngine)
    monkeypatch.setattr(main_module, "build_demo_report", fake_report)
    monkeypatch.setattr(
        "sys.argv",
        ["crypto13", "live-research", "--candidate-source", "production_like_raw", "--max-iterations", "1"],
    )

    main_module.main()

    assert captured["data_root"] == tmp_path
    assert captured["report_out"] == tmp_path / "demo_reports"
    assert captured["latest_report"] == tmp_path / "demo_reports/report.md"
