"""Phase extraction and reconciliation contracts for L2 memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(slots=True)
class ContradictionHint:
    """LLM- or rule-generated hint that a record may need revalidation."""

    target_record_id: str
    target_record_type: str
    contradiction_kind: str
    confidence: float
    evidence_text: str
    recommended_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StructuredEntityHint:
    """Structured entity hint supplied by a source integration."""

    mention_text: str
    entity_type: str
    canonical_name_hint: str | None = None
    resolved_entity_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StructuredGraphHint:
    """Structured graph hint supplied by a source integration."""

    subject_ref: str
    predicate: str
    object_ref: str
    object_type: str
    subject_type: str | None = None
    fact_kind: str | None = None
    confidence: float | None = None
    evidence_text: str | None = None
    origin_mode: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StructuredGraphHint":
        return cls(
            subject_ref=str(payload.get("subject_ref", "")),
            predicate=str(payload.get("predicate", "")),
            object_ref=str(payload.get("object_ref", "")),
            object_type=str(payload.get("object_type", "")),
            subject_type=_optional_text(payload.get("subject_type")),
            fact_kind=_optional_text(payload.get("fact_kind")),
            confidence=float(payload["confidence"])
            if payload.get("confidence") is not None
            else None,
            evidence_text=_optional_text(payload.get("evidence_text")),
            origin_mode=_optional_text(payload.get("origin_mode")),
            attributes=dict(payload.get("attributes", {}))
            if isinstance(payload.get("attributes"), dict)
            else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReconciledTraitOutcome:
    """Stable serialization of one reconcile decision."""

    entity_id: str
    entity_type: str
    trait_name: str
    winning_value: str
    status: str
    confidence: float
    evidence_event_ids: list[str]
    time_span_hours: float
    stability_kind: str
    recommended_snapshot_field: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    subject_ref: str = ""
    subject_type: str = "user"
    predicate: str = ""
    object_ref: str = ""
    object_type: str = ""
    fact_kind: str = ""
    polarity: str = "positive"
    specificity: str = "concrete"
    evidence_text: str = ""
    confidence: float = 0.0
    supporting_event_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase1FactClaim":
        return cls(
            subject_ref=payload.get("subject_ref", ""),
            subject_type=payload.get("subject_type", "user"),
            predicate=payload.get("predicate", ""),
            object_ref=payload.get("object_ref", ""),
            object_type=payload.get("object_type", ""),
            fact_kind=payload.get("fact_kind", ""),
            polarity=payload.get("polarity", "positive"),
            specificity=payload.get("specificity", "concrete"),
            evidence_text=payload.get("evidence_text", ""),
            confidence=payload.get("confidence", 0.0),
            supporting_event_ids=payload.get("supporting_event_ids", []),
        )

    def __post_init__(self) -> None:
        self.subject_ref = _optional_text(self.subject_ref) or ""
        self.subject_type = _optional_text(self.subject_type) or "user"
        self.predicate = _optional_text(self.predicate) or ""
        self.object_ref = _optional_text(self.object_ref) or ""
        self.object_type = _optional_text(self.object_type) or ""
        self.fact_kind = _optional_text(self.fact_kind) or ""
        self.polarity = _optional_text(self.polarity) or "positive"
        self.specificity = _optional_text(self.specificity) or "concrete"
        self.evidence_text = _optional_text(self.evidence_text) or ""
        self.confidence = float(self.confidence or 0.0)
        self.supporting_event_ids = [
            str(s).strip() for s in self.supporting_event_ids if str(s).strip()
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


@dataclass(slots=True)
class L2Phase2GraphEdge:
    """Graph edge produced by Phase 2 integration."""

    subject_ref: str = ""
    subject_type: str = "user"
    predicate: str = ""
    object_ref: str = ""
    object_type: str = ""
    fact_kind: str = ""
    polarity: str = "positive"
    confidence: float = 0.0
    evidence_text: str = ""
    supporting_event_ids: list[str] = field(default_factory=list)
    relationship_to_existing: str = "new"
    related_existing_triple_id: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase2GraphEdge":
        return cls(
            subject_ref=payload.get("subject_ref", ""),
            subject_type=payload.get("subject_type", "user"),
            predicate=payload.get("predicate", ""),
            object_ref=payload.get("object_ref", ""),
            object_type=payload.get("object_type", ""),
            fact_kind=payload.get("fact_kind", ""),
            polarity=payload.get("polarity", "positive"),
            confidence=payload.get("confidence", 0.0),
            evidence_text=payload.get("evidence_text", ""),
            supporting_event_ids=payload.get("supporting_event_ids", []),
            relationship_to_existing=payload.get("relationship_to_existing", "new"),
            related_existing_triple_id=payload.get("related_existing_triple_id"),
        )

    def __post_init__(self) -> None:
        self.subject_ref = _optional_text(self.subject_ref) or ""
        self.subject_type = _optional_text(self.subject_type) or "user"
        self.predicate = _optional_text(self.predicate) or ""
        self.object_ref = _optional_text(self.object_ref) or ""
        self.object_type = _optional_text(self.object_type) or ""
        self.fact_kind = _optional_text(self.fact_kind) or ""
        self.polarity = _optional_text(self.polarity) or "positive"
        self.confidence = float(self.confidence or 0.0)
        self.evidence_text = _optional_text(self.evidence_text) or ""
        self.supporting_event_ids = [
            str(s).strip() for s in self.supporting_event_ids if str(s).strip()
        ]
        self.relationship_to_existing = _optional_text(self.relationship_to_existing) or "new"
        self.related_existing_triple_id = _optional_text(self.related_existing_triple_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2Phase2Refinement:
    """Refinement link produced by Phase 2 when a concrete fact refines a vague one."""

    existing_triple_id: str = ""
    refined_by_object: str = ""
    explanation: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase2Refinement":
        return cls(
            existing_triple_id=payload.get("existing_triple_id", ""),
            refined_by_object=payload.get("refined_by_object", ""),
            explanation=payload.get("explanation", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2Phase2AssertionCandidate:
    """ToM assertion candidate produced by Phase 2."""

    entity_ref: str = ""
    entity_type: str = "user"
    trait_family: str = ""
    trait_name: str = ""
    trait_value: str = ""
    inference_depth: str = "topology_only"
    volatility_index: float = 0.5
    confidence: float = 0.0
    evidence_texts: list[str] = field(default_factory=list)
    supporting_event_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase2AssertionCandidate":
        return cls(
            entity_ref=payload.get("entity_ref", ""),
            entity_type=payload.get("entity_type", "user"),
            trait_family=payload.get("trait_family", ""),
            trait_name=payload.get("trait_name", ""),
            trait_value=str(payload.get("trait_value", "")),
            inference_depth=payload.get("inference_depth", "topology_only"),
            volatility_index=payload.get("volatility_index", 0.5),
            confidence=payload.get("confidence", 0.0),
            evidence_texts=payload.get("evidence_texts", []),
            supporting_event_ids=payload.get("supporting_event_ids", []),
        )

    def __post_init__(self) -> None:
        self.entity_ref = _optional_text(self.entity_ref) or ""
        self.entity_type = _optional_text(self.entity_type) or "user"
        self.trait_family = _optional_text(self.trait_family) or ""
        self.trait_name = _optional_text(self.trait_name) or ""
        self.trait_value = str(self.trait_value)
        self.inference_depth = _optional_text(self.inference_depth) or "topology_only"
        self.volatility_index = float(self.volatility_index or 0.5)
        self.confidence = float(self.confidence or 0.0)
        self.evidence_texts = [str(s).strip() for s in self.evidence_texts if str(s).strip()]
        self.supporting_event_ids = [
            str(s).strip() for s in self.supporting_event_ids if str(s).strip()
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2Phase2ContradictionHint:
    """Contradiction hint produced by Phase 2."""

    target_record_id: str = ""
    target_record_type: str = ""
    contradiction_kind: str = ""
    confidence: float = 0.0
    evidence_text: str = ""
    recommended_action: str = "revalidate_only"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase2ContradictionHint":
        return cls(
            target_record_id=payload.get("target_record_id", ""),
            target_record_type=payload.get("target_record_type", ""),
            contradiction_kind=payload.get("contradiction_kind", ""),
            confidence=payload.get("confidence", 0.0),
            evidence_text=payload.get("evidence_text", ""),
            recommended_action=payload.get("recommended_action", "revalidate_only"),
        )

    def __post_init__(self) -> None:
        self.target_record_id = _optional_text(self.target_record_id) or ""
        self.target_record_type = _optional_text(self.target_record_type) or ""
        self.contradiction_kind = _optional_text(self.contradiction_kind) or ""
        self.confidence = float(self.confidence or 0.0)
        self.evidence_text = _optional_text(self.evidence_text) or ""
        self.recommended_action = _optional_text(self.recommended_action) or "revalidate_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2Phase2Result:
    """Full Phase 2 integration result."""

    graph_edges: list[L2Phase2GraphEdge] = field(default_factory=list)
    refinements: list[L2Phase2Refinement] = field(default_factory=list)
    assertion_candidates: list[L2Phase2AssertionCandidate] = field(default_factory=list)
    contradiction_hints: list[L2Phase2ContradictionHint] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2Phase2Result":
        return cls(
            graph_edges=[
                L2Phase2GraphEdge.from_dict(e)
                for e in payload.get("graph_edges", [])
                if isinstance(e, dict)
            ],
            refinements=[
                L2Phase2Refinement.from_dict(r)
                for r in payload.get("refinements", [])
                if isinstance(r, dict)
            ],
            assertion_candidates=[
                L2Phase2AssertionCandidate.from_dict(a)
                for a in payload.get("assertion_candidates", [])
                if isinstance(a, dict)
            ],
            contradiction_hints=[
                L2Phase2ContradictionHint.from_dict(h)
                for h in payload.get("contradiction_hints", [])
                if isinstance(h, dict)
            ],
        )

    def __post_init__(self) -> None:
        normalized_edges: list[L2Phase2GraphEdge] = []
        for edge_item in self.graph_edges:
            if isinstance(edge_item, L2Phase2GraphEdge):
                normalized_edges.append(edge_item)
            elif isinstance(edge_item, dict):
                normalized_edges.append(L2Phase2GraphEdge.from_dict(edge_item))
        self.graph_edges = normalized_edges

        normalized_refinements: list[L2Phase2Refinement] = []
        for refinement_item in self.refinements:
            if isinstance(refinement_item, L2Phase2Refinement):
                normalized_refinements.append(refinement_item)
            elif isinstance(refinement_item, dict):
                normalized_refinements.append(L2Phase2Refinement.from_dict(refinement_item))
        self.refinements = normalized_refinements

        normalized_assertions: list[L2Phase2AssertionCandidate] = []
        for assertion_item in self.assertion_candidates:
            if isinstance(assertion_item, L2Phase2AssertionCandidate):
                normalized_assertions.append(assertion_item)
            elif isinstance(assertion_item, dict):
                normalized_assertions.append(L2Phase2AssertionCandidate.from_dict(assertion_item))
        self.assertion_candidates = normalized_assertions

        normalized_hints: list[L2Phase2ContradictionHint] = []
        for hint_item in self.contradiction_hints:
            if isinstance(hint_item, L2Phase2ContradictionHint):
                normalized_hints.append(hint_item)
            elif isinstance(hint_item, dict):
                normalized_hints.append(L2Phase2ContradictionHint.from_dict(hint_item))
        self.contradiction_hints = normalized_hints

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_edges": [e.to_dict() for e in self.graph_edges],
            "refinements": [r.to_dict() for r in self.refinements],
            "assertion_candidates": [a.to_dict() for a in self.assertion_candidates],
            "contradiction_hints": [h.to_dict() for h in self.contradiction_hints],
        }

    @property
    def has_content(self) -> bool:
        return bool(self.graph_edges or self.assertion_candidates or self.contradiction_hints)


__all__ = [
    "ContradictionHint",
    "L2Phase1Entity",
    "L2Phase1FactClaim",
    "L2Phase1ResolvedRef",
    "L2Phase1Result",
    "L2Phase2AssertionCandidate",
    "L2Phase2ContradictionHint",
    "L2Phase2GraphEdge",
    "L2Phase2Refinement",
    "L2Phase2Result",
    "ReconciledTraitOutcome",
    "StructuredEntityHint",
    "StructuredGraphHint",
]
