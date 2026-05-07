"""Candidate and extraction result contracts for L2 memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .context_bundle import ResolvedContextRef


def _non_empty_text(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must not be blank")
    return text


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


@dataclass(slots=True)
class L2AssertionCandidate:
    """Typed assertion candidate extracted from a unified L2 prompt."""

    entity_ref: str = ""
    entity_type: str = "user"
    trait_family: str = ""
    trait_name: str = ""
    trait_value: Any = ""
    natural_summary: str = ""
    target_ref: str = ""
    target_entity_id: str = ""
    target_entity_type: str = ""
    inference_depth: str = ""
    volatility_index: float = 0.5
    confidence: float = 0.0
    validation_state: str = "tentative"
    evidence_texts: list[str] = field(default_factory=list)
    supporting_event_ids: list[str] = field(default_factory=list)
    temporal_scope: str = ""
    decay_policy: str = ""
    expires_at: float | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2AssertionCandidate":
        return cls(
            entity_ref=payload.get("entity_ref", ""),
            entity_type=payload.get("entity_type", "user"),
            trait_family=payload.get("trait_family", ""),
            trait_name=payload.get("trait_name", ""),
            trait_value=payload.get("trait_value", ""),
            natural_summary=str(payload.get("natural_summary", "") or "")[:500],
            target_ref=payload.get("target_ref", ""),
            target_entity_id=payload.get("target_entity_id", ""),
            target_entity_type=payload.get("target_entity_type", ""),
            inference_depth=payload.get("inference_depth", ""),
            volatility_index=payload.get("volatility_index", 0.5),
            confidence=payload.get("confidence", 0.0),
            validation_state=payload.get("validation_state", "tentative"),
            evidence_texts=payload.get("evidence_texts", []),
            supporting_event_ids=payload.get("supporting_event_ids", []),
            temporal_scope=payload.get("temporal_scope", ""),
            decay_policy=payload.get("decay_policy", ""),
            expires_at=payload.get("expires_at"),
        )

    def __post_init__(self) -> None:
        self.entity_ref = _optional_text(self.entity_ref) or ""
        self.entity_type = _optional_text(self.entity_type) or "user"
        self.trait_family = _optional_text(self.trait_family) or ""
        self.trait_name = _optional_text(self.trait_name) or ""
        self.target_ref = _optional_text(self.target_ref) or ""
        self.target_entity_id = _optional_text(self.target_entity_id) or ""
        self.target_entity_type = _optional_text(self.target_entity_type) or ""
        self.inference_depth = _optional_text(self.inference_depth) or ""
        self.volatility_index = float(self.volatility_index or 0.5)
        self.confidence = float(self.confidence or 0.0)
        self.validation_state = _optional_text(self.validation_state) or "tentative"
        self.evidence_texts = [
            str(item).strip() for item in self.evidence_texts if str(item).strip()
        ]
        self.supporting_event_ids = [
            str(item).strip() for item in self.supporting_event_ids if str(item).strip()
        ]
        self.temporal_scope = _optional_text(self.temporal_scope) or ""
        self.decay_policy = _optional_text(self.decay_policy) or ""
        expires_at_value: Any = self.expires_at
        self.expires_at = None if expires_at_value in (None, "") else float(expires_at_value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2CandidateSet:
    """Typed candidate bundle used between extraction and arbitration."""

    graph_candidates: list[L2GraphCandidate] = field(default_factory=list)
    assertion_candidates: list[L2AssertionCandidate] = field(default_factory=list)

    def __post_init__(self) -> None:
        normalized_graph_candidates: list[L2GraphCandidate] = []
        for graph_item in self.graph_candidates:
            if isinstance(graph_item, L2GraphCandidate):
                normalized_graph_candidates.append(graph_item)
            elif isinstance(graph_item, dict):
                normalized_graph_candidates.append(L2GraphCandidate.from_dict(graph_item))
        normalized_assertion_candidates: list[L2AssertionCandidate] = []
        for assertion_item in self.assertion_candidates:
            if isinstance(assertion_item, L2AssertionCandidate):
                normalized_assertion_candidates.append(assertion_item)
            elif isinstance(assertion_item, dict):
                normalized_assertion_candidates.append(
                    L2AssertionCandidate.from_dict(assertion_item)
                )
        self.graph_candidates = normalized_graph_candidates
        self.assertion_candidates = normalized_assertion_candidates

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_candidates": [item.to_dict() for item in self.graph_candidates],
            "assertion_candidates": [item.to_dict() for item in self.assertion_candidates],
        }


@dataclass(slots=True)
class L2UnifiedExtractionResult:
    """Normalized typed result returned by unified extraction."""

    mentions: list[dict[str, Any]] = field(default_factory=list)
    resolved_context_refs: list[ResolvedContextRef] = field(default_factory=list)
    graph_candidates: list[L2GraphCandidate] = field(default_factory=list)
    assertion_candidates: list[L2AssertionCandidate] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=lambda: {"entity_status": "none"})

    def __post_init__(self) -> None:
        self.mentions = [dict(item) for item in self.mentions if isinstance(item, dict)]
        normalized_resolved_context_refs: list[ResolvedContextRef] = []
        for ref_item in self.resolved_context_refs:
            if isinstance(ref_item, ResolvedContextRef):
                normalized_resolved_context_refs.append(ref_item)
            elif isinstance(ref_item, dict):
                normalized_resolved_context_refs.append(
                    ResolvedContextRef(
                        surface=str(ref_item.get("surface") or "").strip(),
                        reference_type=str(ref_item.get("reference_type") or "unresolved").strip()
                        or "unresolved",
                        resolved_ref=str(ref_item.get("resolved_ref") or "").strip(),
                        resolved_kind=str(ref_item.get("resolved_kind") or "").strip(),
                        confidence=float(ref_item.get("confidence", 0.0) or 0.0),
                        evidence_text=str(ref_item.get("evidence_text") or "").strip(),
                    )
                )
        self.resolved_context_refs = [
            item for item in normalized_resolved_context_refs if item.surface
        ]
        self.graph_candidates = L2CandidateSet(
            graph_candidates=self.graph_candidates
        ).graph_candidates
        self.assertion_candidates = L2CandidateSet(
            assertion_candidates=self.assertion_candidates
        ).assertion_candidates
        self.diagnostics = (
            dict(self.diagnostics)
            if isinstance(self.diagnostics, dict)
            else {"entity_status": "none"}
        )
        if not self.diagnostics.get("entity_status"):
            self.diagnostics["entity_status"] = "none"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resolved_context_refs"] = [item.to_dict() for item in self.resolved_context_refs]
        payload["graph_candidates"] = [item.to_dict() for item in self.graph_candidates]
        payload["assertion_candidates"] = [item.to_dict() for item in self.assertion_candidates]
        return payload


@dataclass(slots=True)
class L2ConflictArbitrationResult:
    """Typed final arbitration decision for severe L2 conflicts."""

    decision: str
    winning_record_ids: list[str] = field(default_factory=list)
    superseded_record_ids: list[str] = field(default_factory=list)
    reason: str = ""

    def __post_init__(self) -> None:
        self.decision = _non_empty_text(self.decision, field_name="decision")
        self.winning_record_ids = [
            str(item).strip() for item in self.winning_record_ids if str(item).strip()
        ]
        self.superseded_record_ids = [
            str(item).strip() for item in self.superseded_record_ids if str(item).strip()
        ]
        self.reason = str(self.reason or "").strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "L2AssertionCandidate",
    "L2CandidateSet",
    "L2ConflictArbitrationResult",
    "L2GraphCandidate",
    "L2UnifiedExtractionResult",
]
