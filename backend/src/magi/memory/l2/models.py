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
class L2CandidateSet:
    """Typed candidate bundle used between extraction and arbitration."""

    graph_candidates: list[dict[str, Any]] = field(default_factory=list)
    assertion_candidates: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.graph_candidates = [dict(item) for item in self.graph_candidates if isinstance(item, dict)]
        self.assertion_candidates = [dict(item) for item in self.assertion_candidates if isinstance(item, dict)]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2UnifiedExtractionResult:
    """Normalized typed result returned by unified extraction."""

    mentions: list[dict[str, Any]] = field(default_factory=list)
    resolved_context_refs: list[ResolvedContextRef] = field(default_factory=list)
    graph_candidates: list[dict[str, Any]] = field(default_factory=list)
    assertion_candidates: list[dict[str, Any]] = field(default_factory=list)
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
        self.graph_candidates = [dict(item) for item in self.graph_candidates if isinstance(item, dict)]
        self.assertion_candidates = [dict(item) for item in self.assertion_candidates if isinstance(item, dict)]
        self.diagnostics = dict(self.diagnostics) if isinstance(self.diagnostics, dict) else {"entity_status": "none"}
        if not self.diagnostics.get("entity_status"):
            self.diagnostics["entity_status"] = "none"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resolved_context_refs"] = [item.to_dict() for item in self.resolved_context_refs]
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
    "L2BatchJob",
    "L2CandidateSet",
    "L2ConflictArbitrationResult",
    "L2EntityReconcileJob",
    "L2EventWindow",
    "L2EventWindowSummary",
    "L2PendingBatchBucket",
    "L2SnapshotRefreshJob",
    "L2UnifiedExtractionResult",
    "ManualL2EventRequest",
    "ReconciledTraitOutcome",
    "ResolvedEntityMention",
    "StructuredEntityHint",
    "StructuredGraphHint",
]
