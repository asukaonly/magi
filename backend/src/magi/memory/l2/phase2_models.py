"""Phase 2 inference contracts for L2 memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .phase_model_utils import _optional_text


@dataclass(slots=True)
class L2Phase2ClaimAssessment:
    """Non-obvious relationship between a grounded claim and an existing record."""

    claim_id: str = ""
    relationship: str = ""
    related_record_id: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase2ClaimAssessment":
        return cls(
            claim_id=payload.get("claim_id", ""),
            relationship=payload.get("relationship", ""),
            related_record_id=payload.get("related_record_id", ""),
        )

    def __post_init__(self) -> None:
        self.claim_id = _optional_text(self.claim_id) or ""
        self.relationship = (_optional_text(self.relationship) or "").casefold()
        self.related_record_id = _optional_text(self.related_record_id) or ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2Phase2AssertionCandidate:
    """Higher-order assertion proposed from grounded Phase 1 claims."""

    entity_ref: str = ""
    entity_type: str = "user"
    trait_family: str = ""
    trait_name: str = ""
    trait_value: str = ""
    natural_summary: str = ""
    supporting_claim_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase2AssertionCandidate":
        return cls(
            entity_ref=payload.get("entity_ref", ""),
            entity_type=payload.get("entity_type", "user"),
            trait_family=payload.get("trait_family", ""),
            trait_name=payload.get("trait_name", ""),
            trait_value=str(payload.get("trait_value", ""))[:40],
            natural_summary=str(payload.get("natural_summary", "") or "")[:500],
            supporting_claim_ids=payload.get("supporting_claim_ids", []),
        )

    def __post_init__(self) -> None:
        self.entity_ref = _optional_text(self.entity_ref) or ""
        self.entity_type = _optional_text(self.entity_type) or "user"
        self.trait_family = _optional_text(self.trait_family) or ""
        self.trait_name = _optional_text(self.trait_name) or ""
        self.trait_value = str(self.trait_value)
        self.natural_summary = str(self.natural_summary or "")[:500]
        self.supporting_claim_ids = _unique_texts(self.supporting_claim_ids)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2Phase2Result:
    """Full Phase 2 inference result."""

    claim_assessments: list[L2Phase2ClaimAssessment] = field(default_factory=list)
    assertion_candidates: list[L2Phase2AssertionCandidate] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase2Result":
        return cls(
            claim_assessments=[
                L2Phase2ClaimAssessment.from_dict(item)
                for item in payload.get("claim_assessments", [])
                if isinstance(item, dict)
            ],
            assertion_candidates=[
                L2Phase2AssertionCandidate.from_dict(item)
                for item in payload.get("assertion_candidates", [])
                if isinstance(item, dict)
            ],
        )

    def __post_init__(self) -> None:
        self.claim_assessments = [
            item
            if isinstance(item, L2Phase2ClaimAssessment)
            else L2Phase2ClaimAssessment.from_dict(item)
            for item in self.claim_assessments
            if isinstance(item, (L2Phase2ClaimAssessment, dict))
        ]
        self.assertion_candidates = [
            item
            if isinstance(item, L2Phase2AssertionCandidate)
            else L2Phase2AssertionCandidate.from_dict(item)
            for item in self.assertion_candidates
            if isinstance(item, (L2Phase2AssertionCandidate, dict))
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_assessments": [item.to_dict() for item in self.claim_assessments],
            "assertion_candidates": [item.to_dict() for item in self.assertion_candidates],
        }

    @property
    def has_content(self) -> bool:
        return bool(self.claim_assessments or self.assertion_candidates)


def _unique_texts(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


__all__ = [
    "L2Phase2AssertionCandidate",
    "L2Phase2ClaimAssessment",
    "L2Phase2Result",
]
