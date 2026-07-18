import pytest

from src.candidate_sources import (
    CandidateSourceType,
    DirectionSupport,
    PRODUCTION_LIKE_RAW_METADATA,
    SIMPLIFIED_PLACEHOLDER_METADATA,
    build_candidate_from_new_entry_model,
    build_candidate_from_production_baseline_export,
    ensure_supported_candidate_source,
    supported_candidate_sources,
)


def test_candidate_source_types_are_declared():
    assert supported_candidate_sources() == {
        CandidateSourceType.SIMPLIFIED_PLACEHOLDER.value,
        CandidateSourceType.PRODUCTION_LIKE_RAW.value,
        CandidateSourceType.PRODUCTION_BASELINE_EXPORT.value,
        CandidateSourceType.NEW_ENTRY_MODEL_ADAPTER.value,
    }


def test_simplified_placeholder_metadata_contract():
    metadata = SIMPLIFIED_PLACEHOLDER_METADATA

    assert metadata.candidate_source == "simplified_placeholder"
    assert metadata.candidate_source_version == "v1"
    assert metadata.is_placeholder is True
    assert metadata.edge_conclusions_allowed is False
    assert metadata.direction_support == DirectionSupport.LONG_AND_SHORT.value
    assert "technical live paper smoke" in metadata.source_description


def test_production_like_raw_metadata_contract():
    metadata = PRODUCTION_LIKE_RAW_METADATA

    assert metadata.candidate_source == "production_like_raw"
    assert metadata.candidate_source_version == "v2"
    assert metadata.is_placeholder is False
    assert metadata.edge_conclusions_allowed is False
    assert metadata.direction_support == DirectionSupport.LONG_ONLY.value
    assert metadata.source_description == (
        "Production-like raw LONG candidate source before hard-gate rejection for sandbox research"
    )


def test_unsupported_candidate_source_raises_clear_error():
    with pytest.raises(ValueError, match="Unsupported candidate_source"):
        ensure_supported_candidate_source("production_runtime_import")


def test_future_candidate_source_stubs_do_not_implement_strategy_or_import_production():
    with pytest.raises(NotImplementedError, match="does not import production"):
        build_candidate_from_production_baseline_export()

    with pytest.raises(NotImplementedError, match="does not implement a new entry strategy"):
        build_candidate_from_new_entry_model()
