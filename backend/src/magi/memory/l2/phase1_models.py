"""Phase 1 extraction contracts for L2 memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .phase_model_utils import _optional_text


class L2TemporalCue(str, Enum):
    """Linguistic time horizon explicitly grounded in source wording."""

    ONE_OFF = "one_off"
    RECENT = "recent"
    RECURRING = "recurring"
    STABLE = "stable"
    UNSPECIFIED = "unspecified"

    @classmethod
    def from_value(cls, value: "L2TemporalCue | str | None") -> "L2TemporalCue":
        if isinstance(value, cls):
            return value
        normalized = str(value or "").strip().casefold() or cls.UNSPECIFIED.value
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(f"Unsupported L2 temporal cue: {value}") from exc


@dataclass(slots=True)
class L2Phase1Entity:
    """Entity extracted and resolved during Phase 1."""

    surface: str = ""
    normalized_name: str = ""
    entity_type: str = ""
    specificity: str = "concrete"
    resolved_id: str | None = None
    is_new: bool = True
    alias_signals: list[str] = field(default_factory=list)
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase1Entity":
        return cls(
            surface=payload.get("surface", ""),
            normalized_name=payload.get("normalized_name", ""),
            entity_type=payload.get("entity_type", ""),
            specificity=payload.get("specificity", "concrete"),
            resolved_id=payload.get("resolved_id"),
            is_new=payload.get("is_new", True),
            alias_signals=payload.get("alias_signals", []),
            confidence=payload.get("confidence", 0.0),
        )

    def __post_init__(self) -> None:
        self.surface = _optional_text(self.surface) or ""
        self.normalized_name = _optional_text(self.normalized_name) or self.surface
        self.entity_type = _optional_text(self.entity_type) or ""
        self.specificity = _optional_text(self.specificity) or "concrete"
        self.resolved_id = _optional_text(self.resolved_id)
        self.is_new = bool(self.is_new)
        self.alias_signals = [str(s).strip() for s in self.alias_signals if str(s).strip()]
        self.confidence = float(self.confidence or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2Phase1FactClaim:
    """Fact claim extracted during Phase 1."""

    claim_id: str = ""
    subject_ref: str = ""
    subject_type: str = "user"
    predicate: str = ""
    object_ref: str = ""
    object_type: str = ""
    fact_kind: str = ""
    temporal_cue: L2TemporalCue | str = L2TemporalCue.UNSPECIFIED
    polarity: str = "positive"
    specificity: str = "concrete"
    evidence_text: str = ""
    confidence: float = 0.0
    supporting_event_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase1FactClaim":
        return cls(
            claim_id="",
            subject_ref=payload.get("subject_ref", ""),
            subject_type=payload.get("subject_type", "user"),
            predicate=payload.get("predicate", ""),
            object_ref=payload.get("object_ref", ""),
            object_type=payload.get("object_type", ""),
            fact_kind=payload.get("fact_kind", ""),
            temporal_cue=payload.get("temporal_cue", L2TemporalCue.UNSPECIFIED.value),
            polarity=payload.get("polarity", "positive"),
            specificity=payload.get("specificity", "concrete"),
            evidence_text=payload.get("evidence_text", ""),
            confidence=payload.get("confidence", 0.0),
            supporting_event_ids=payload.get("supporting_event_ids", []),
        )

    def __post_init__(self) -> None:
        self.claim_id = _optional_text(self.claim_id) or ""
        self.subject_ref = _optional_text(self.subject_ref) or ""
        self.subject_type = _optional_text(self.subject_type) or "user"
        self.predicate = _optional_text(self.predicate) or ""
        self.object_ref = _optional_text(self.object_ref) or ""
        self.object_type = _optional_text(self.object_type) or ""
        self.fact_kind = _optional_text(self.fact_kind) or ""
        self.temporal_cue = L2TemporalCue.from_value(self.temporal_cue)
        self.polarity = _optional_text(self.polarity) or "positive"
        self.specificity = _optional_text(self.specificity) or "concrete"
        self.evidence_text = _optional_text(self.evidence_text) or ""
        self.confidence = float(self.confidence or 0.0)
        self.supporting_event_ids = [
            str(s).strip() for s in self.supporting_event_ids if str(s).strip()
        ]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["temporal_cue"] = self.temporal_cue.value
        return payload


@dataclass(slots=True)
class L2Phase1ResolvedRef:
    """Resolved pronoun/reference from Phase 1."""

    surface: str = ""
    resolved_ref: str | None = None
    resolved_kind: str | None = None
    reference_type: str = "unresolved"
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase1ResolvedRef":
        return cls(
            surface=payload.get("surface", ""),
            resolved_ref=payload.get("resolved_ref"),
            resolved_kind=payload.get("resolved_kind"),
            reference_type=payload.get("reference_type", "unresolved"),
            confidence=payload.get("confidence", 0.0),
        )

    def __post_init__(self) -> None:
        self.surface = _optional_text(self.surface) or ""
        self.resolved_ref = _optional_text(self.resolved_ref)
        self.resolved_kind = _optional_text(self.resolved_kind)
        self.reference_type = _optional_text(self.reference_type) or "unresolved"
        self.confidence = float(self.confidence or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2Phase1Result:
    """Full Phase 1 extraction result."""

    entities: list[L2Phase1Entity] = field(default_factory=list)
    fact_claims: list[L2Phase1FactClaim] = field(default_factory=list)
    resolved_refs: list[L2Phase1ResolvedRef] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=lambda: {"entity_status": "none"})

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase1Result":
        return cls(
            entities=[
                L2Phase1Entity.from_dict(e)
                for e in payload.get("entities", [])
                if isinstance(e, dict)
            ],
            fact_claims=[
                L2Phase1FactClaim.from_dict(f)
                for f in payload.get("fact_claims", [])
                if isinstance(f, dict)
            ],
            resolved_refs=[
                L2Phase1ResolvedRef.from_dict(r)
                for r in payload.get("resolved_refs", [])
                if isinstance(r, dict)
            ],
            diagnostics=payload.get("diagnostics", {"entity_status": "none"}),
        )

    def __post_init__(self) -> None:
        normalized_entities: list[L2Phase1Entity] = []
        for entity_item in self.entities:
            if isinstance(entity_item, L2Phase1Entity):
                normalized_entities.append(entity_item)
            elif isinstance(entity_item, dict):
                normalized_entities.append(L2Phase1Entity.from_dict(entity_item))
        self.entities = normalized_entities

        normalized_facts: list[L2Phase1FactClaim] = []
        for fact_item in self.fact_claims:
            if isinstance(fact_item, L2Phase1FactClaim):
                normalized_facts.append(fact_item)
            elif isinstance(fact_item, dict):
                normalized_facts.append(L2Phase1FactClaim.from_dict(fact_item))
        self.fact_claims = normalized_facts

        normalized_refs: list[L2Phase1ResolvedRef] = []
        for ref_item in self.resolved_refs:
            if isinstance(ref_item, L2Phase1ResolvedRef):
                normalized_refs.append(ref_item)
            elif isinstance(ref_item, dict):
                normalized_refs.append(L2Phase1ResolvedRef.from_dict(ref_item))
        self.resolved_refs = normalized_refs

        self.diagnostics = (
            dict(self.diagnostics)
            if isinstance(self.diagnostics, dict)
            else {"entity_status": "none"}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "fact_claims": [f.to_dict() for f in self.fact_claims],
            "resolved_refs": [r.to_dict() for r in self.resolved_refs],
            "diagnostics": dict(self.diagnostics),
        }

    @property
    def has_content(self) -> bool:
        return bool(self.entities or self.fact_claims)


__all__ = [
    "L2Phase1Entity",
    "L2Phase1FactClaim",
    "L2Phase1ResolvedRef",
    "L2Phase1Result",
    "L2TemporalCue",
]
