from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CandidateSourceType(str, Enum):
    SIMPLIFIED_PLACEHOLDER = "simplified_placeholder"
    PRODUCTION_LIKE_RAW = "production_like_raw"
    PRODUCTION_BASELINE_EXPORT = "production_baseline_export"
    NEW_ENTRY_MODEL_ADAPTER = "new_entry_model_adapter"


class DirectionSupport(str, Enum):
    LONG_ONLY = "LONG_ONLY"
    SHORT_ONLY = "SHORT_ONLY"
    LONG_AND_SHORT = "LONG_AND_SHORT"


PLACEHOLDER_EDGE_WARNING = "technical smoke source only; do not use for edge conclusions"


@dataclass(frozen=True)
class CandidateSourceMetadata:
    candidate_source: str
    candidate_source_version: str
    is_placeholder: bool
    edge_conclusions_allowed: bool
    direction_support: str
    source_description: str

    def as_candidate_kwargs(self) -> dict[str, Any]:
        return {
            "candidate_source": self.candidate_source,
            "candidate_source_version": self.candidate_source_version,
            "is_placeholder": self.is_placeholder,
            "edge_conclusions_allowed": self.edge_conclusions_allowed,
            "direction_support": self.direction_support,
            "source_description": self.source_description,
        }

    def as_status_fields(self) -> dict[str, Any]:
        return {
            "candidate_source": self.candidate_source,
            "candidate_source_version": self.candidate_source_version,
            "is_placeholder": self.is_placeholder,
            "candidate_source_is_placeholder": self.is_placeholder,
            "edge_conclusions_allowed": self.edge_conclusions_allowed,
            "candidate_source_warning": PLACEHOLDER_EDGE_WARNING if self.is_placeholder else "",
            "direction_support": self.direction_support,
            "source_description": self.source_description,
        }


SIMPLIFIED_PLACEHOLDER_METADATA = CandidateSourceMetadata(
    candidate_source=CandidateSourceType.SIMPLIFIED_PLACEHOLDER.value,
    candidate_source_version="v1",
    is_placeholder=True,
    edge_conclusions_allowed=False,
    direction_support=DirectionSupport.LONG_AND_SHORT.value,
    source_description="MA/ATR simplified placeholder for technical live paper smoke testing only",
)

PRODUCTION_LIKE_RAW_METADATA = CandidateSourceMetadata(
    candidate_source=CandidateSourceType.PRODUCTION_LIKE_RAW.value,
    candidate_source_version="v2",
    is_placeholder=False,
    edge_conclusions_allowed=False,
    direction_support=DirectionSupport.LONG_ONLY.value,
    source_description="Production-like raw LONG candidate source before hard-gate rejection for sandbox research",
)

JOURNAL_REPLAY_METADATA = CandidateSourceMetadata(
    candidate_source=CandidateSourceType.PRODUCTION_BASELINE_EXPORT.value,
    candidate_source_version="legacy_journal_v1",
    is_placeholder=False,
    edge_conclusions_allowed=True,
    direction_support=DirectionSupport.LONG_AND_SHORT.value,
    source_description="Closed-trades journal replay/export adapter for historical baseline research",
)


def supported_candidate_sources() -> set[str]:
    return {item.value for item in CandidateSourceType}


def metadata_for_candidate_source(candidate_source: str) -> CandidateSourceMetadata:
    ensure_supported_candidate_source(candidate_source)
    if candidate_source == CandidateSourceType.SIMPLIFIED_PLACEHOLDER.value:
        return SIMPLIFIED_PLACEHOLDER_METADATA
    if candidate_source == CandidateSourceType.PRODUCTION_LIKE_RAW.value:
        return PRODUCTION_LIKE_RAW_METADATA
    if candidate_source == CandidateSourceType.PRODUCTION_BASELINE_EXPORT.value:
        return JOURNAL_REPLAY_METADATA
    raise NotImplementedError(
        f"{candidate_source} is declared as a future boundary but is not implemented as a live candidate source."
    )


def ensure_supported_candidate_source(candidate_source: str) -> None:
    if candidate_source not in supported_candidate_sources():
        raise ValueError(f"Unsupported candidate_source: {candidate_source}")


def build_candidate_from_production_baseline_export(*args: Any, **kwargs: Any) -> None:
    raise NotImplementedError(
        "production_baseline_export is a future candidate source boundary only; "
        "Task 5C-B does not import production files or production code."
    )


def build_candidate_from_new_entry_model(*args: Any, **kwargs: Any) -> None:
    raise NotImplementedError(
        "new_entry_model_adapter is a future candidate source boundary only; "
        "Task 5C-B does not implement a new entry strategy."
    )
