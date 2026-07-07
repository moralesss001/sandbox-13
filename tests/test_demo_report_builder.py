from src.demo_report_builder import build_demo_report


def test_demo_report_includes_placeholder_candidate_source_warning(tmp_path):
    report = build_demo_report(
        {
            "metrics": {},
            "portfolios": {},
            "candidate_source": "simplified_placeholder",
            "candidate_source_version": "v1",
            "edge_conclusions_allowed": False,
            "live_direction_policy": "LONG_ONLY",
            "candidate_source_warning": "technical smoke source only; do not use for edge conclusions",
        },
        out_dir=tmp_path,
        signal_source="research_simplified_live",
    )

    text = report.read_text(encoding="utf-8")

    assert "candidate_source = simplified_placeholder" in text
    assert "candidate_source_version = v1" in text
    assert "edge_conclusions_allowed = False" in text
    assert "technical smoke source only; do not use for edge conclusions" in text
