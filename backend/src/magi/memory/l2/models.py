"""Contracts for the asynchronous L2 cognition pipeline."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

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


def build_l2_batch_bucket_key(*, session_id: str | None, user_id: str | None) -> str | None:
    normalized_session_id = _optional_text(session_id)
    if normalized_session_id is not None:
        return f"session:{normalized_session_id}"
    normalized_user_id = _optional_text(user_id)
    if normalized_user_id is not None:
        return f"user:{normalized_user_id}"
    return None


@dataclass(slots=True)
class L2EventWindowSummary:
    """Summary metadata for one typed L2 event window."""

    event_count: int = 0
    session_id: str | None = None
    user_id: str | None = None
    history_context_count: int = 0

    def __post_init__(self) -> None:
        self.event_count = max(0, int(self.event_count))
        self.session_id = _optional_text(self.session_id)
        self.user_id = _optional_text(self.user_id)
        self.history_context_count = max(0, int(self.history_context_count))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2EventWindow:
    """Typed extraction window passed through the L2 pipeline."""

    event_ids: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    context_texts: list[str] = field(default_factory=list)
    history_contexts: list[dict[str, Any]] = field(default_factory=list)
    summary: L2EventWindowSummary = field(default_factory=L2EventWindowSummary)

    def __post_init__(self) -> None:
        normalized_events = [dict(item) for item in self.events if isinstance(item, dict)]
        normalized_event_ids = [str(item).strip() for item in self.event_ids if str(item).strip()]
        if not normalized_event_ids:
            normalized_event_ids = [
                str(item.get("event_id", "")).strip()
                for item in normalized_events
                if str(item.get("event_id", "")).strip()
            ]
        normalized_texts = [str(item) for item in self.texts if str(item).strip()]
        if not normalized_texts:
            normalized_texts = [
                str(item.get("content", "")).strip()
                for item in normalized_events
                if str(item.get("content", "")).strip()
            ]
        if not isinstance(self.summary, L2EventWindowSummary):
            self.summary = L2EventWindowSummary(**dict(self.summary))
        if self.summary.event_count <= 0:
            self.summary.event_count = max(len(normalized_event_ids), len(normalized_events), len(normalized_texts))
        if self.summary.history_context_count <= 0 and self.history_contexts:
            self.summary.history_context_count = len(self.history_contexts)

        self.event_ids = normalized_event_ids
        self.events = normalized_events
        self.texts = normalized_texts
        self.context_texts = [str(item) for item in self.context_texts if str(item).strip()]
        self.history_contexts = [dict(item) for item in self.history_contexts if isinstance(item, dict)]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = self.summary.to_dict()
        return payload


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
        self.evidence_texts = [str(item).strip() for item in self.evidence_texts if str(item).strip()]
        self.supporting_event_ids = [str(item).strip() for item in self.supporting_event_ids if str(item).strip()]
        self.temporal_scope = _optional_text(self.temporal_scope) or ""
        self.decay_policy = _optional_text(self.decay_policy) or ""
        self.expires_at = None if self.expires_at in (None, "") else float(self.expires_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2CandidateSet:
    """Typed candidate bundle used between extraction and arbitration."""

    graph_candidates: list[L2GraphCandidate] = field(default_factory=list)
    assertion_candidates: list[L2AssertionCandidate] = field(default_factory=list)

    def __post_init__(self) -> None:
        normalized_graph_candidates: list[L2GraphCandidate] = []
        for item in self.graph_candidates:
            if isinstance(item, L2GraphCandidate):
                normalized_graph_candidates.append(item)
            elif isinstance(item, dict):
                normalized_graph_candidates.append(L2GraphCandidate.from_dict(item))
        normalized_assertion_candidates: list[L2AssertionCandidate] = []
        for item in self.assertion_candidates:
            if isinstance(item, L2AssertionCandidate):
                normalized_assertion_candidates.append(item)
            elif isinstance(item, dict):
                normalized_assertion_candidates.append(L2AssertionCandidate.from_dict(item))
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
        for item in self.resolved_context_refs:
            if isinstance(item, ResolvedContextRef):
                normalized_resolved_context_refs.append(item)
            elif isinstance(item, dict):
                normalized_resolved_context_refs.append(
                    ResolvedContextRef(
                        surface=str(item.get("surface") or "").strip(),
                        reference_type=str(item.get("reference_type") or "unresolved").strip() or "unresolved",
                        resolved_ref=str(item.get("resolved_ref") or "").strip(),
                        resolved_kind=str(item.get("resolved_kind") or "").strip(),
                        confidence=float(item.get("confidence", 0.0) or 0.0),
                        evidence_text=str(item.get("evidence_text") or "").strip(),
                    )
                )
        self.resolved_context_refs = [item for item in normalized_resolved_context_refs if item.surface]
        self.graph_candidates = L2CandidateSet(graph_candidates=self.graph_candidates).graph_candidates
        self.assertion_candidates = L2CandidateSet(assertion_candidates=self.assertion_candidates).assertion_candidates
        self.diagnostics = dict(self.diagnostics) if isinstance(self.diagnostics, dict) else {"entity_status": "none"}
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
        self.winning_record_ids = [str(item).strip() for item in self.winning_record_ids if str(item).strip()]
        self.superseded_record_ids = [str(item).strip() for item in self.superseded_record_ids if str(item).strip()]
        self.reason = str(self.reason or "").strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResolvedEntityMention:
    """Typed resolved entity mention used inside the L2 pipeline."""

    mention_text: str
    normalized_surface: str
    entity_type: str | None
    resolved_entity_id: str | None
    confidence: float | None

    def __post_init__(self) -> None:
        self.mention_text = _non_empty_text(self.mention_text, field_name="mention_text")
        self.normalized_surface = _non_empty_text(
            self.normalized_surface or self.mention_text,
            field_name="normalized_surface",
        )
        self.entity_type = _optional_text(self.entity_type)
        self.resolved_entity_id = _optional_text(self.resolved_entity_id)
        self.confidence = None if self.confidence is None else float(self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2FocalEntityRef:
    """Typed entity reference used when loading contradiction context."""

    entity_id: str
    entity_type: str

    def __post_init__(self) -> None:
        self.entity_id = _non_empty_text(self.entity_id, field_name="entity_id")
        self.entity_type = _non_empty_text(self.entity_type, field_name="entity_type")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2KnowledgeEdgeWrite:
    """Normalized knowledge-edge payload ready for L2 persistence."""

    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    evidence_event_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    observed_at: float = 0.0
    source_type: str = "unknown"
    extraction_method: str = "rule"

    def __post_init__(self) -> None:
        self.subject_id = _non_empty_text(self.subject_id, field_name="subject_id")
        self.subject_type = _non_empty_text(self.subject_type, field_name="subject_type")
        self.predicate = _non_empty_text(self.predicate, field_name="predicate")
        self.object_id = _non_empty_text(self.object_id, field_name="object_id")
        self.object_type = _non_empty_text(self.object_type, field_name="object_type")
        self.evidence_event_ids = [str(item).strip() for item in self.evidence_event_ids if str(item).strip()]
        self.confidence = float(self.confidence or 0.0)
        self.observed_at = float(self.observed_at or 0.0)
        self.source_type = _optional_text(self.source_type) or "unknown"
        self.extraction_method = _optional_text(self.extraction_method) or "rule"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2TomAssertionWrite:
    """Normalized ToM assertion payload ready for L2 persistence."""

    entity_id: str
    entity_type: str
    trait_name: str
    trait_value: str
    confidence_score: float = 0.0
    evidence_events: list[str] = field(default_factory=list)
    volatility_index: float = 0.5
    source_domain: str = ""
    inference_depth: str = ""
    validation_state: str = "tentative"
    first_inferred_at: float = 0.0
    last_validated_at: float = 0.0
    trait_family: str = ""
    target_entity_id: str = ""
    target_entity_type: str = ""
    target_scope: str = "global"
    temporal_scope: str = ""
    decay_policy: str = ""
    decay_anchor_at: float = 0.0
    context_ref_id: str = ""
    expires_at: float | None = None

    def __post_init__(self) -> None:
        self.entity_id = _non_empty_text(self.entity_id, field_name="entity_id")
        self.entity_type = _non_empty_text(self.entity_type, field_name="entity_type")
        self.trait_name = _non_empty_text(self.trait_name, field_name="trait_name")
        self.trait_value = str(self.trait_value)
        self.confidence_score = float(self.confidence_score or 0.0)
        self.evidence_events = [str(item).strip() for item in self.evidence_events if str(item).strip()]
        self.volatility_index = float(self.volatility_index or 0.5)
        self.source_domain = _optional_text(self.source_domain) or ""
        self.inference_depth = _optional_text(self.inference_depth) or ""
        self.validation_state = _optional_text(self.validation_state) or "tentative"
        self.first_inferred_at = float(self.first_inferred_at or 0.0)
        self.last_validated_at = float(self.last_validated_at or 0.0)
        self.trait_family = _optional_text(self.trait_family) or ""
        self.target_entity_id = _optional_text(self.target_entity_id) or ""
        self.target_entity_type = _optional_text(self.target_entity_type) or ""
        self.target_scope = _optional_text(self.target_scope) or "global"
        self.temporal_scope = _optional_text(self.temporal_scope) or ""
        self.decay_policy = _optional_text(self.decay_policy) or ""
        self.decay_anchor_at = float(self.decay_anchor_at or 0.0)
        self.context_ref_id = _optional_text(self.context_ref_id) or ""
        self.expires_at = None if self.expires_at in (None, "") else float(self.expires_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2ExistingRecord:
    """Normalized existing record payload used for contradiction checks."""

    record_id: str
    record_type: str
    entity_id: str = ""
    entity_type: str = ""
    trait_name: str = ""
    trait_value: str = ""
    validation_state: str = ""
    subject_id: str = ""
    predicate: str = ""
    object_id: str = ""
    status: str = ""
    confidence: float = 0.0
    evidence_event_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2ExistingRecord":
        return cls(
            record_id=payload.get("record_id", ""),
            record_type=payload.get("record_type", ""),
            entity_id=payload.get("entity_id", ""),
            entity_type=payload.get("entity_type", ""),
            trait_name=payload.get("trait_name", ""),
            trait_value=payload.get("trait_value", ""),
            validation_state=payload.get("validation_state", ""),
            subject_id=payload.get("subject_id", ""),
            predicate=payload.get("predicate", ""),
            object_id=payload.get("object_id", ""),
            status=payload.get("status", ""),
            confidence=payload.get("confidence", 0.0),
            evidence_event_ids=payload.get("evidence_event_ids", []),
        )

    def __post_init__(self) -> None:
        self.record_id = _non_empty_text(self.record_id, field_name="record_id")
        self.record_type = _non_empty_text(self.record_type, field_name="record_type")
        self.entity_id = _optional_text(self.entity_id) or ""
        self.entity_type = _optional_text(self.entity_type) or ""
        self.trait_name = _optional_text(self.trait_name) or ""
        self.trait_value = _optional_text(self.trait_value) or ""
        self.validation_state = _optional_text(self.validation_state) or ""
        self.subject_id = _optional_text(self.subject_id) or ""
        self.predicate = _optional_text(self.predicate) or ""
        self.object_id = _optional_text(self.object_id) or ""
        self.status = _optional_text(self.status) or ""
        self.confidence = float(self.confidence or 0.0)
        self.evidence_event_ids = [str(item).strip() for item in self.evidence_event_ids if str(item).strip()]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2SourceEvent:
    """Normalized evidence event payload used during conflict arbitration."""

    event_id: str
    timestamp: float
    source: str
    event_type: str
    content: str
    author_type: str = "user"
    session_id: str | None = None
    user_id: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2SourceEvent":
        return cls(
            event_id=payload.get("event_id", ""),
            timestamp=payload.get("timestamp", 0.0),
            source=payload.get("source", "unknown"),
            event_type=payload.get("event_type", ""),
            content=payload.get("content", ""),
            author_type=payload.get("author_type", "user"),
            session_id=payload.get("session_id"),
            user_id=payload.get("user_id"),
        )

    def __post_init__(self) -> None:
        self.event_id = _non_empty_text(self.event_id, field_name="event_id")
        self.timestamp = float(self.timestamp or 0.0)
        self.source = _optional_text(self.source) or "unknown"
        self.event_type = _optional_text(self.event_type) or ""
        self.content = str(self.content or "")
        self.author_type = _optional_text(self.author_type) or "user"
        self.session_id = _optional_text(self.session_id)
        self.user_id = _optional_text(self.user_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2EntityResolution:
    """Normalized entity resolution result returned by the L2 LLM service."""

    decision: str = "unresolved"
    matched_entity_id: str | None = None
    matched_entity_name: str | None = None
    confidence: float = 0.0
    reason_tags: list[str] = field(default_factory=list)
    should_merge: bool = False
    canonical_name_suggestion: str | None = None

    def __post_init__(self) -> None:
        self.decision = _optional_text(self.decision) or "unresolved"
        self.matched_entity_id = _optional_text(self.matched_entity_id)
        self.matched_entity_name = _optional_text(self.matched_entity_name)
        self.confidence = float(self.confidence or 0.0)
        self.reason_tags = [str(item).strip() for item in self.reason_tags if str(item).strip()]
        self.should_merge = bool(self.should_merge)
        self.canonical_name_suggestion = _optional_text(self.canonical_name_suggestion)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2EntityResolutionMention:
    """Typed entity-resolution mention payload."""

    mention_text: str
    entity_type: str | None = None
    context_text: str | None = None

    def __post_init__(self) -> None:
        self.mention_text = _non_empty_text(self.mention_text, field_name="mention_text")
        self.entity_type = _optional_text(self.entity_type)
        self.context_text = _optional_text(self.context_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2EntityCandidate:
    """Typed candidate entity payload used for L2 resolution prompts."""

    entity_id: str
    canonical_name: str
    entity_type: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2EntityCandidate":
        return cls(
            entity_id=payload.get("entity_id", ""),
            canonical_name=payload.get("canonical_name", ""),
            entity_type=payload.get("entity_type", ""),
        )

    def __post_init__(self) -> None:
        self.entity_id = _non_empty_text(self.entity_id, field_name="entity_id")
        self.canonical_name = _non_empty_text(self.canonical_name, field_name="canonical_name")
        self.entity_type = _non_empty_text(self.entity_type, field_name="entity_type")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2ReconcileEntity:
    """Typed entity payload used for reconcile prompts."""

    entity_id: str
    entity_type: str

    def __post_init__(self) -> None:
        self.entity_id = _non_empty_text(self.entity_id, field_name="entity_id")
        self.entity_type = _non_empty_text(self.entity_type, field_name="entity_type")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2ReconcileGraphFact:
    """Typed graph-fact payload used for reconcile prompts."""

    predicate: str
    object_id: str
    subject_id: str = ""
    status: str = ""
    confidence: float = 0.0

    def __post_init__(self) -> None:
        self.predicate = _non_empty_text(self.predicate, field_name="predicate")
        self.object_id = _non_empty_text(self.object_id, field_name="object_id")
        self.subject_id = _optional_text(self.subject_id) or ""
        self.status = _optional_text(self.status) or ""
        self.confidence = float(self.confidence or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2ReconcileAssertion:
    """Typed assertion payload used for reconcile prompts."""

    trait_name: str
    trait_value: str
    validation_state: str = ""
    confidence: float = 0.0
    evidence_event_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.trait_name = _non_empty_text(self.trait_name, field_name="trait_name")
        self.trait_value = str(self.trait_value)
        self.validation_state = _optional_text(self.validation_state) or ""
        self.confidence = float(self.confidence or 0.0)
        self.evidence_event_ids = [str(item).strip() for item in self.evidence_event_ids if str(item).strip()]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2BatchJob:
    """Queue payload for one flushed L2 microbatch."""

    job_id: str
    bucket_key: str
    events: list[dict[str, Any]]
    flush_reason: str
    estimated_tokens: int
    session_id: str | None = None
    user_id: str | None = None
    job_type: str = "extract_batch"
    oldest_event_timestamp: float = 0.0
    newest_event_timestamp: float = 0.0

    def __post_init__(self) -> None:
        self.job_id = _non_empty_text(self.job_id, field_name="job_id")
        self.bucket_key = _non_empty_text(self.bucket_key, field_name="bucket_key")
        self.flush_reason = _non_empty_text(self.flush_reason, field_name="flush_reason")
        self.session_id = _optional_text(self.session_id)
        self.user_id = _optional_text(self.user_id)
        self.estimated_tokens = max(0, int(self.estimated_tokens))
        self.events = sorted(
            [dict(item) for item in self.events if isinstance(item, dict)],
            key=lambda item: (float(item.get("timestamp", 0.0) or 0.0), str(item.get("event_id", ""))),
        )
        if not self.events:
            raise ValueError("events must not be empty")
        timestamps = [float(item.get("timestamp", 0.0) or 0.0) for item in self.events]
        self.oldest_event_timestamp = float(self.oldest_event_timestamp or min(timestamps))
        self.newest_event_timestamp = float(self.newest_event_timestamp or max(timestamps))

    @property
    def event_ids(self) -> list[str]:
        return [str(item.get("event_id", "")).strip() for item in self.events if str(item.get("event_id", "")).strip()]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event_ids"] = self.event_ids
        return payload


@dataclass(slots=True)
class L2PendingBatchBucket:
    """In-memory staging bucket used before L2 microbatch flush."""

    bucket_key: str
    session_id: str | None = None
    user_id: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    estimated_tokens: int = 0
    oldest_event_timestamp: float = 0.0
    newest_event_timestamp: float = 0.0
    created_at: float = 0.0
    last_event_at: float = 0.0
    is_flushing: bool = False

    def __post_init__(self) -> None:
        self.bucket_key = _non_empty_text(self.bucket_key, field_name="bucket_key")
        self.session_id = _optional_text(self.session_id)
        self.user_id = _optional_text(self.user_id)
        self.estimated_tokens = max(0, int(self.estimated_tokens))
        self.events = [dict(item) for item in self.events if isinstance(item, dict)]
        if self.events:
            enqueued_at = float(self.created_at or self.last_event_at or time.time())
            timestamps = [float(item.get("timestamp", 0.0) or 0.0) for item in self.events]
            self.oldest_event_timestamp = float(self.oldest_event_timestamp or min(timestamps))
            self.newest_event_timestamp = float(self.newest_event_timestamp or max(timestamps))
            self.created_at = float(self.created_at or enqueued_at)
            self.last_event_at = float(self.last_event_at or enqueued_at)

    @classmethod
    def for_owner(cls, *, session_id: str | None = None, user_id: str | None = None) -> "L2PendingBatchBucket":
        bucket_key = build_l2_batch_bucket_key(session_id=session_id, user_id=user_id)
        if bucket_key is None:
            raise ValueError("session_id or user_id is required")
        return cls(bucket_key=bucket_key, session_id=session_id, user_id=user_id)

    def add_event(self, event: dict[str, Any], *, estimated_tokens: int, queued_at: float | None = None) -> None:
        payload = dict(event)
        event_id = _non_empty_text(str(payload.get("event_id", "")), field_name="event_id")
        timestamp = float(payload.get("timestamp", 0.0) or 0.0)
        enqueued_at = float(time.time() if queued_at is None else queued_at)
        payload["event_id"] = event_id
        payload["timestamp"] = timestamp
        self.events.append(payload)
        self.estimated_tokens += max(0, int(estimated_tokens))
        if not self.created_at:
            self.created_at = enqueued_at
        self.last_event_at = enqueued_at
        if not self.oldest_event_timestamp or timestamp < self.oldest_event_timestamp:
            self.oldest_event_timestamp = timestamp
        if timestamp > self.newest_event_timestamp:
            self.newest_event_timestamp = timestamp

    def build_job(self, *, flush_reason: str, job_id: str | None = None) -> "L2BatchJob":
        resolved_job_id = _optional_text(job_id) or f"{self.bucket_key}:{int(self.newest_event_timestamp * 1000)}"
        return L2BatchJob(
            job_id=resolved_job_id,
            bucket_key=self.bucket_key,
            events=self.events,
            flush_reason=flush_reason,
            estimated_tokens=self.estimated_tokens,
            session_id=self.session_id,
            user_id=self.user_id,
            oldest_event_timestamp=self.oldest_event_timestamp,
            newest_event_timestamp=self.newest_event_timestamp,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2EntityReconcileJob:
    """Queue payload for entity-level reconcile."""

    entity_ids: list[str]
    job_type: str = "reconcile"
    batch_key: str = field(init=False)

    def __post_init__(self) -> None:
        normalized = sorted({_non_empty_text(entity_id, field_name="entity_id") for entity_id in self.entity_ids})
        if not normalized:
            raise ValueError("entity_ids must not be empty")
        self.entity_ids = normalized
        self.batch_key = "entities:" + "|".join(normalized)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2SnapshotRefreshJob:
    """Queue payload for snapshot refresh work."""

    entity_ids: list[str]
    reason: str = "reconcile"
    job_type: str = "snapshot_refresh"
    batch_key: str = field(init=False)

    def __post_init__(self) -> None:
        normalized = sorted({_non_empty_text(entity_id, field_name="entity_id") for entity_id in self.entity_ids})
        if not normalized:
            raise ValueError("entity_ids must not be empty")
        self.entity_ids = normalized
        self.batch_key = "snapshots:" + "|".join(normalized)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ManualL2EventRequest:
    """User-supplied manual event used by the L2 lab."""

    text: str
    user_id: str
    session_id: Optional[str] = None
    source: str = "l2_lab"
    cognition_eligible: bool = True
    entity_focus_hint: Optional[str] = None

    def __post_init__(self) -> None:
        self.text = _non_empty_text(self.text, field_name="text")
        self.user_id = _non_empty_text(self.user_id, field_name="user_id")
        if self.session_id is not None:
            self.session_id = self.session_id.strip() or None
        if self.entity_focus_hint is not None:
            self.entity_focus_hint = self.entity_focus_hint.strip() or None
        self.source = self.source.strip() or "l2_lab"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    canonical_name_hint: Optional[str] = None
    resolved_entity_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StructuredGraphHint:
    """Structured graph hint supplied by a source integration."""

    subject_ref: str
    predicate: str
    object_ref: str
    object_type: str
    subject_type: Optional[str] = None
    evidence_text: Optional[str] = None

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


__all__ = [
    "build_l2_batch_bucket_key",
    "ContradictionHint",
    "L2AssertionCandidate",
    "L2BatchJob",
    "L2CandidateSet",
    "L2ConflictArbitrationResult",
    "L2EntityCandidate",
    "L2EntityResolution",
    "L2EntityResolutionMention",
    "L2EntityReconcileJob",
    "L2ExistingRecord",
    "L2ReconcileAssertion",
    "L2ReconcileEntity",
    "L2ReconcileGraphFact",
    "L2EventWindow",
    "L2EventWindowSummary",
    "L2FocalEntityRef",
    "L2GraphCandidate",
    "L2KnowledgeEdgeWrite",
    "L2PendingBatchBucket",
    "L2SnapshotRefreshJob",
    "L2SourceEvent",
    "L2TomAssertionWrite",
    "L2UnifiedExtractionResult",
    "ManualL2EventRequest",
    "ReconciledTraitOutcome",
    "ResolvedEntityMention",
    "StructuredEntityHint",
    "StructuredGraphHint",
]
