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


def build_l2_batch_bucket_key(
    *,
    session_id: str | None,
    user_id: str | None,
    owner_key: str | None = None,
) -> str | None:
    normalized_session_id = _optional_text(session_id)
    if normalized_session_id is not None:
        return f"session:{normalized_session_id}"
    normalized_user_id = _optional_text(user_id)
    if normalized_user_id is not None:
        return f"user:{normalized_user_id}"
    normalized_owner_key = _optional_text(owner_key)
    if normalized_owner_key is not None:
        return f"owner:{normalized_owner_key}"
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
class L2BatchEvent:
    """Typed event payload used inside L2 prompt windows."""

    event_id: str
    content: str
    timestamp: float = 0.0
    session_id: str | None = None
    user_id: str | None = None
    source: str = "unknown"
    event_type: str = ""
    author_type: str = "user"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2BatchEvent":
        return cls(
            event_id=payload.get("event_id", ""),
            content=payload.get("content", ""),
            timestamp=payload.get("timestamp", 0.0),
            session_id=payload.get("session_id"),
            user_id=payload.get("user_id"),
            source=payload.get("source", "unknown"),
            event_type=payload.get("event_type", ""),
            author_type=payload.get("author_type", "user"),
        )

    def __post_init__(self) -> None:
        self.event_id = _non_empty_text(self.event_id, field_name="event_id")
        self.content = str(self.content or "")
        self.timestamp = float(self.timestamp or 0.0)
        self.session_id = _optional_text(self.session_id)
        self.user_id = _optional_text(self.user_id)
        self.source = _optional_text(self.source) or "unknown"
        self.event_type = _optional_text(self.event_type) or ""
        self.author_type = _optional_text(self.author_type) or "user"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2HistoryContext:
    """Typed recalled history context included in L2 extraction prompts."""

    event_id: str
    content: str
    timestamp: float = 0.0
    session_id: str | None = None
    matched_entity_id: str | None = None
    matched_text: str | None = None
    canonical_name: str | None = None
    match_source: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2HistoryContext":
        return cls(
            event_id=payload.get("event_id", ""),
            content=payload.get("content", ""),
            timestamp=payload.get("timestamp", 0.0),
            session_id=payload.get("session_id"),
            matched_entity_id=payload.get("matched_entity_id"),
            matched_text=payload.get("matched_text"),
            canonical_name=payload.get("canonical_name"),
            match_source=payload.get("match_source"),
        )

    def __post_init__(self) -> None:
        self.event_id = _non_empty_text(self.event_id, field_name="event_id")
        self.content = _non_empty_text(self.content, field_name="content")
        self.timestamp = float(self.timestamp or 0.0)
        self.session_id = _optional_text(self.session_id)
        self.matched_entity_id = _optional_text(self.matched_entity_id)
        self.matched_text = _optional_text(self.matched_text)
        self.canonical_name = _optional_text(self.canonical_name)
        self.match_source = _optional_text(self.match_source)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2EventWindow:
    """Typed extraction window passed through the L2 pipeline."""

    event_ids: list[str] = field(default_factory=list)
    events: list[L2BatchEvent] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    context_texts: list[str] = field(default_factory=list)
    history_contexts: list[L2HistoryContext] = field(default_factory=list)
    summary: L2EventWindowSummary = field(default_factory=L2EventWindowSummary)

    def __post_init__(self) -> None:
        normalized_events: list[L2BatchEvent] = []
        for item in self.events:
            if isinstance(item, L2BatchEvent):
                normalized_events.append(item)
            elif isinstance(item, dict):
                normalized_events.append(L2BatchEvent.from_dict(item))
        normalized_event_ids = [str(item).strip() for item in self.event_ids if str(item).strip()]
        if not normalized_event_ids:
            normalized_event_ids = [
                str(item.event_id).strip()
                for item in normalized_events
                if str(item.event_id).strip()
            ]
        normalized_texts = [str(item) for item in self.texts if str(item).strip()]
        if not normalized_texts:
            normalized_texts = [
                str(item.content).strip()
                for item in normalized_events
                if str(item.content).strip()
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
        normalized_history_contexts: list[L2HistoryContext] = []
        for item in self.history_contexts:
            if isinstance(item, L2HistoryContext):
                normalized_history_contexts.append(item)
            elif isinstance(item, dict):
                normalized_history_contexts.append(L2HistoryContext.from_dict(item))
        self.history_contexts = normalized_history_contexts

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["events"] = [item.to_dict() for item in self.events]
        payload["history_contexts"] = [item.to_dict() for item in self.history_contexts]
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
class L2BatchEntityResolutionItem:
    """One mention + its candidates for batch entity resolution."""

    mention_key: str
    mention: L2EntityResolutionMention
    candidate_entities: list[L2EntityCandidate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mention_key": self.mention_key,
            "mention": self.mention.to_dict(),
            "candidate_entities": [c.to_dict() for c in self.candidate_entities],
        }


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
    max_events: int | None = None
    max_estimated_tokens: int | None = None
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
        self.max_events = max(1, int(self.max_events)) if self.max_events is not None else None
        self.max_estimated_tokens = (
            max(1, int(self.max_estimated_tokens))
            if self.max_estimated_tokens is not None
            else None
        )
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
    def for_owner(
        cls,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        owner_key: str | None = None,
        max_events: int | None = None,
        max_estimated_tokens: int | None = None,
    ) -> "L2PendingBatchBucket":
        bucket_key = build_l2_batch_bucket_key(
            session_id=session_id,
            user_id=user_id,
            owner_key=owner_key,
        )
        if bucket_key is None:
            raise ValueError("session_id, user_id, or owner_key is required")
        return cls(
            bucket_key=bucket_key,
            session_id=session_id,
            user_id=user_id,
            max_events=max_events,
            max_estimated_tokens=max_estimated_tokens,
        )

    def add_event(
        self,
        event: dict[str, Any],
        *,
        estimated_tokens: int,
        queued_at: float | None = None,
        max_events: int | None = None,
        max_estimated_tokens: int | None = None,
    ) -> None:
        payload = dict(event)
        event_id = _non_empty_text(str(payload.get("event_id", "")), field_name="event_id")
        timestamp = float(payload.get("timestamp", 0.0) or 0.0)
        enqueued_at = float(time.time() if queued_at is None else queued_at)
        payload["event_id"] = event_id
        payload["timestamp"] = timestamp
        self.events.append(payload)
        if max_events is not None:
            resolved_max_events = max(1, int(max_events))
            self.max_events = (
                resolved_max_events
                if self.max_events is None
                else min(self.max_events, resolved_max_events)
            )
        if max_estimated_tokens is not None:
            resolved_max_tokens = max(1, int(max_estimated_tokens))
            self.max_estimated_tokens = (
                resolved_max_tokens
                if self.max_estimated_tokens is None
                else min(self.max_estimated_tokens, resolved_max_tokens)
            )
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
    fact_kind: Optional[str] = None
    confidence: Optional[float] = None
    evidence_text: Optional[str] = None
    origin_mode: Optional[str] = None
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
            confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
            evidence_text=_optional_text(payload.get("evidence_text")),
            origin_mode=_optional_text(payload.get("origin_mode")),
            attributes=dict(payload.get("attributes", {})) if isinstance(payload.get("attributes"), dict) else {},
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


# ---------------------------------------------------------------------------
# Phase 1 — Extract & Resolve result models
# ---------------------------------------------------------------------------


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
        self.supporting_event_ids = [str(s).strip() for s in self.supporting_event_ids if str(s).strip()]

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
            entities=[L2Phase1Entity.from_dict(e) for e in payload.get("entities", []) if isinstance(e, dict)],
            fact_claims=[L2Phase1FactClaim.from_dict(f) for f in payload.get("fact_claims", []) if isinstance(f, dict)],
            resolved_refs=[L2Phase1ResolvedRef.from_dict(r) for r in payload.get("resolved_refs", []) if isinstance(r, dict)],
            diagnostics=payload.get("diagnostics", {"entity_status": "none"}),
        )

    def __post_init__(self) -> None:
        normalized_entities: list[L2Phase1Entity] = []
        for item in self.entities:
            if isinstance(item, L2Phase1Entity):
                normalized_entities.append(item)
            elif isinstance(item, dict):
                normalized_entities.append(L2Phase1Entity.from_dict(item))
        self.entities = normalized_entities

        normalized_facts: list[L2Phase1FactClaim] = []
        for item in self.fact_claims:
            if isinstance(item, L2Phase1FactClaim):
                normalized_facts.append(item)
            elif isinstance(item, dict):
                normalized_facts.append(L2Phase1FactClaim.from_dict(item))
        self.fact_claims = normalized_facts

        normalized_refs: list[L2Phase1ResolvedRef] = []
        for item in self.resolved_refs:
            if isinstance(item, L2Phase1ResolvedRef):
                normalized_refs.append(item)
            elif isinstance(item, dict):
                normalized_refs.append(L2Phase1ResolvedRef.from_dict(item))
        self.resolved_refs = normalized_refs

        self.diagnostics = dict(self.diagnostics) if isinstance(self.diagnostics, dict) else {"entity_status": "none"}

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


# ---------------------------------------------------------------------------
# Phase 2 — Integrate & Reason result models
# ---------------------------------------------------------------------------


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
        self.supporting_event_ids = [str(s).strip() for s in self.supporting_event_ids if str(s).strip()]
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
        self.supporting_event_ids = [str(s).strip() for s in self.supporting_event_ids if str(s).strip()]

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
            graph_edges=[L2Phase2GraphEdge.from_dict(e) for e in payload.get("graph_edges", []) if isinstance(e, dict)],
            refinements=[L2Phase2Refinement.from_dict(r) for r in payload.get("refinements", []) if isinstance(r, dict)],
            assertion_candidates=[L2Phase2AssertionCandidate.from_dict(a) for a in payload.get("assertion_candidates", []) if isinstance(a, dict)],
            contradiction_hints=[L2Phase2ContradictionHint.from_dict(h) for h in payload.get("contradiction_hints", []) if isinstance(h, dict)],
        )

    def __post_init__(self) -> None:
        normalized_edges: list[L2Phase2GraphEdge] = []
        for item in self.graph_edges:
            if isinstance(item, L2Phase2GraphEdge):
                normalized_edges.append(item)
            elif isinstance(item, dict):
                normalized_edges.append(L2Phase2GraphEdge.from_dict(item))
        self.graph_edges = normalized_edges

        normalized_refinements: list[L2Phase2Refinement] = []
        for item in self.refinements:
            if isinstance(item, L2Phase2Refinement):
                normalized_refinements.append(item)
            elif isinstance(item, dict):
                normalized_refinements.append(L2Phase2Refinement.from_dict(item))
        self.refinements = normalized_refinements

        normalized_assertions: list[L2Phase2AssertionCandidate] = []
        for item in self.assertion_candidates:
            if isinstance(item, L2Phase2AssertionCandidate):
                normalized_assertions.append(item)
            elif isinstance(item, dict):
                normalized_assertions.append(L2Phase2AssertionCandidate.from_dict(item))
        self.assertion_candidates = normalized_assertions

        normalized_hints: list[L2Phase2ContradictionHint] = []
        for item in self.contradiction_hints:
            if isinstance(item, L2Phase2ContradictionHint):
                normalized_hints.append(item)
            elif isinstance(item, dict):
                normalized_hints.append(L2Phase2ContradictionHint.from_dict(item))
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


# ── Episode Models ────────────────────────────────────────────────


@dataclass(slots=True)
class EpisodeWrite:
    """Payload for creating or extending an episode."""

    episode_id: str
    episode_type: str = "activity"
    status: str = "candidate"
    time_start: float = 0.0
    time_end: float = 0.0
    parent_episode_id: str = ""
    label: str = ""
    summary: str = ""
    dominant_mode: str = ""
    primary_entity_ids: list[str] = field(default_factory=list)
    primary_place_ids: list[str] = field(default_factory=list)
    primary_topic_keys: list[str] = field(default_factory=list)
    continuity_signals: list[str] = field(default_factory=list)
    formation_method: str = "time_gap_cluster"
    confidence: float = 0.5
    source_event_count: int = 0
    privacy_scope: str = "private"

    def __post_init__(self) -> None:
        self.episode_id = _non_empty_text(self.episode_id, field_name="episode_id")
        self.episode_type = _optional_text(self.episode_type) or "activity"
        self.status = _optional_text(self.status) or "candidate"
        self.time_start = float(self.time_start or 0.0)
        self.time_end = float(self.time_end or 0.0)
        self.parent_episode_id = _optional_text(self.parent_episode_id) or ""
        self.label = _optional_text(self.label) or ""
        self.summary = _optional_text(self.summary) or ""
        self.dominant_mode = _optional_text(self.dominant_mode) or ""
        self.primary_entity_ids = [str(i).strip() for i in self.primary_entity_ids if str(i).strip()]
        self.primary_place_ids = [str(i).strip() for i in self.primary_place_ids if str(i).strip()]
        self.primary_topic_keys = [str(k).strip() for k in self.primary_topic_keys if str(k).strip()]
        self.continuity_signals = [str(s).strip() for s in self.continuity_signals if str(s).strip()]
        self.formation_method = _optional_text(self.formation_method) or "time_gap_cluster"
        self.confidence = float(self.confidence or 0.5)
        self.source_event_count = int(self.source_event_count or 0)
        self.privacy_scope = _optional_text(self.privacy_scope) or "private"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EpisodeWrite":
        return cls(
            episode_id=str(data.get("episode_id", "")),
            episode_type=str(data.get("episode_type", "activity")),
            status=str(data.get("status", "candidate")),
            time_start=float(data.get("time_start", 0.0)),
            time_end=float(data.get("time_end", 0.0)),
            parent_episode_id=str(data.get("parent_episode_id", "")),
            label=str(data.get("label", "")),
            summary=str(data.get("summary", "")),
            dominant_mode=str(data.get("dominant_mode", "")),
            primary_entity_ids=list(data.get("primary_entity_ids", [])),
            primary_place_ids=list(data.get("primary_place_ids", [])),
            primary_topic_keys=list(data.get("primary_topic_keys", [])),
            continuity_signals=list(data.get("continuity_signals", [])),
            formation_method=str(data.get("formation_method", "time_gap_cluster")),
            confidence=float(data.get("confidence", 0.5)),
            source_event_count=int(data.get("source_event_count", 0)),
            privacy_scope=str(data.get("privacy_scope", "private")),
        )


@dataclass(slots=True)
class EpisodeCandidateJob:
    """Job unit for streaming episode candidate formation."""

    event_id: str
    event_timestamp: float
    event_tags: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    place_ids: list[str] = field(default_factory=list)
    topic_keys: list[str] = field(default_factory=list)
    episode_type_hint: str = "activity"

    def __post_init__(self) -> None:
        self.event_id = _non_empty_text(self.event_id, field_name="event_id")
        self.event_timestamp = float(self.event_timestamp or 0.0)
        self.event_tags = [str(t).strip() for t in self.event_tags if str(t).strip()]
        self.entity_ids = [str(i).strip() for i in self.entity_ids if str(i).strip()]
        self.place_ids = [str(i).strip() for i in self.place_ids if str(i).strip()]
        self.topic_keys = [str(k).strip() for k in self.topic_keys if str(k).strip()]
        self.episode_type_hint = _optional_text(self.episode_type_hint) or "activity"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EpisodeCandidateJob":
        return cls(
            event_id=str(data.get("event_id", "")),
            event_timestamp=float(data.get("event_timestamp", 0.0)),
            event_tags=list(data.get("event_tags", [])),
            entity_ids=list(data.get("entity_ids", [])),
            place_ids=list(data.get("place_ids", [])),
            topic_keys=list(data.get("topic_keys", [])),
            episode_type_hint=str(data.get("episode_type_hint", "activity")),
        )


@dataclass(slots=True)
class EpisodeConsolidationStats:
    """Statistics for a single episode consolidation run."""

    promoted: int = 0
    merged: int = 0
    invalidated: int = 0
    summaries_generated: int = 0
    embeddings_queued: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "build_l2_batch_bucket_key",
    "ContradictionHint",
    "EpisodeCandidateJob",
    "EpisodeConsolidationStats",
    "EpisodeWrite",
    "L2AssertionCandidate",
    "L2BatchEvent",
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
    "L2HistoryContext",
    "L2KnowledgeEdgeWrite",
    "L2PendingBatchBucket",
    "L2Phase1Entity",
    "L2Phase1FactClaim",
    "L2Phase1ResolvedRef",
    "L2Phase1Result",
    "L2Phase2AssertionCandidate",
    "L2Phase2ContradictionHint",
    "L2Phase2GraphEdge",
    "L2Phase2Refinement",
    "L2Phase2Result",
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
