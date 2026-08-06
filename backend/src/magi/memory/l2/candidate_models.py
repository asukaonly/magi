"""Candidate and extraction result contracts for L2 memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(slots=True)
class L2GraphCandidate:
    """Typed graph candidate extracted from a unified L2 prompt."""

    subject_ref: str = ""
    subject_type: str = "user"
    predicate: str = ""
    object_ref: str = ""
    object_type: str = ""
    fact_kind: str = ""
    polarity: str = ""
    evidence_text: str = ""
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2GraphCandidate":
        return cls(
            subject_ref=payload.get("subject_ref", ""),
            subject_type=payload.get("subject_type", "user"),
            predicate=payload.get("predicate", ""),
            object_ref=payload.get("object_ref", ""),
            object_type=payload.get("object_type", ""),
            fact_kind=payload.get("fact_kind", ""),
            polarity=payload.get("polarity", ""),
            evidence_text=payload.get("evidence_text", ""),
            confidence=payload.get("confidence", 0.0),
        )

    def __post_init__(self) -> None:
        self.subject_ref = _optional_text(self.subject_ref) or ""
        self.subject_type = _optional_text(self.subject_type) or "user"
        self.predicate = _optional_text(self.predicate) or ""
        self.object_ref = _optional_text(self.object_ref) or ""
        self.object_type = _optional_text(self.object_type) or ""
        self.fact_kind = _optional_text(self.fact_kind) or ""
        self.polarity = _optional_text(self.polarity) or ""
        self.evidence_text = _optional_text(self.evidence_text) or ""
        self.confidence = float(self.confidence or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["L2GraphCandidate"]
