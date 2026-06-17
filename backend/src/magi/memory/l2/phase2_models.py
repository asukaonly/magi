"""Phase 2 integration contracts for L2 memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .phase_model_utils import _optional_text


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
class L2Phase2AssertionCandidate:
    """ToM assertion candidate produced by Phase 2."""

    entity_ref: str = ""
    entity_type: str = "user"
    trait_family: str = ""
    trait_name: str = ""
    trait_value: str = ""
    natural_summary: str = ""
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
            trait_value=str(payload.get("trait_value", ""))[:40],
            natural_summary=str(payload.get("natural_summary", "") or "")[:500],
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
            "assertion_candidates": [a.to_dict() for a in self.assertion_candidates],
            "contradiction_hints": [h.to_dict() for h in self.contradiction_hints],
        }

    @property
    def has_content(self) -> bool:
        return bool(self.graph_edges or self.assertion_candidates or self.contradiction_hints)


__all__ = [
    "L2Phase2AssertionCandidate",
    "L2Phase2ContradictionHint",
    "L2Phase2GraphEdge",
    "L2Phase2Result",
]
