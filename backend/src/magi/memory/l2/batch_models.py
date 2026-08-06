"""Batch, window, and request contracts for L2 memory."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


PROJECTION_ATTEMPT_DESCRIPTOR_VERSION = 1


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
    source_type: str | None = None,
    owner_key: str | None = None,
) -> str | None:
    normalized_session_id = _optional_text(session_id)
    if normalized_session_id is not None:
        return f"session:{normalized_session_id}"
    normalized_source_type = _optional_text(source_type)
    normalized_owner_key = _optional_text(owner_key)
    normalized_user_id = _optional_text(user_id)
    if normalized_source_type is not None and (
        normalized_owner_key is not None or normalized_user_id is not None
    ):
        parts = [f"source:{normalized_source_type}"]
        if normalized_owner_key is not None:
            parts.append(f"owner:{normalized_owner_key}")
        if normalized_user_id is not None:
            parts.append(f"user:{normalized_user_id}")
        return "|".join(parts)
    if normalized_owner_key is not None:
        parts = [f"owner:{normalized_owner_key}"]
        if normalized_user_id is not None:
            parts.append(f"user:{normalized_user_id}")
        return "|".join(parts)
    if normalized_user_id is not None:
        return f"user:{normalized_user_id}"
    return None


def _current_time() -> float:
    from . import models as models_module

    return float(models_module.time.time())


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
    metadata_json: dict[str, Any] = field(default_factory=dict)

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
            metadata_json=(
                dict(payload.get("metadata_json") or {})
                if isinstance(payload.get("metadata_json"), dict)
                else {}
            ),
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
        self.metadata_json = (
            dict(self.metadata_json) if isinstance(self.metadata_json, dict) else {}
        )

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
        for event_item in self.events:
            if isinstance(event_item, L2BatchEvent):
                normalized_events.append(event_item)
            elif isinstance(event_item, dict):
                normalized_events.append(L2BatchEvent.from_dict(event_item))
        normalized_event_ids = [str(item).strip() for item in self.event_ids if str(item).strip()]
        if not normalized_event_ids:
            normalized_event_ids = [
                str(item.event_id).strip()
                for item in normalized_events
                if str(item.event_id).strip()
            ]
        normalized_texts = [str(item) for item in self.texts]
        if not normalized_texts:
            normalized_texts = [
                str(item.content).strip() for item in normalized_events if str(item.content).strip()
            ]
        if not isinstance(self.summary, L2EventWindowSummary):
            self.summary = L2EventWindowSummary(**dict(self.summary))
        if self.summary.event_count <= 0:
            self.summary.event_count = max(
                len(normalized_event_ids), len(normalized_events), len(normalized_texts)
            )
        if self.summary.history_context_count <= 0 and self.history_contexts:
            self.summary.history_context_count = len(self.history_contexts)

        self.event_ids = normalized_event_ids
        self.events = normalized_events
        self.texts = normalized_texts
        self.context_texts = [str(item) for item in self.context_texts if str(item).strip()]
        normalized_history_contexts: list[L2HistoryContext] = []
        for context_item in self.history_contexts:
            if isinstance(context_item, L2HistoryContext):
                normalized_history_contexts.append(context_item)
            elif isinstance(context_item, dict):
                normalized_history_contexts.append(L2HistoryContext.from_dict(context_item))
        self.history_contexts = normalized_history_contexts

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["events"] = [item.to_dict() for item in self.events]
        payload["history_contexts"] = [item.to_dict() for item in self.history_contexts]
        payload["summary"] = self.summary.to_dict()
        return payload


@dataclass(slots=True)
class L2ProjectionLease:
    """Fencing token for one durable event projection attempt."""

    event_id: str
    lease_token: str
    attempt_count: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2ProjectionLease":
        return cls(
            event_id=str(payload.get("event_id") or ""),
            lease_token=str(payload.get("lease_token") or ""),
            attempt_count=int(payload.get("attempt_count") or 0),
        )

    def __post_init__(self) -> None:
        self.event_id = _non_empty_text(self.event_id, field_name="event_id")
        self.lease_token = _non_empty_text(self.lease_token, field_name="lease_token")
        self.attempt_count = int(self.attempt_count)
        if self.attempt_count < 1:
            raise ValueError("attempt_count must be positive")


def derive_projection_attempt_key(
    leases: Iterable[L2ProjectionLease],
) -> str:
    """Derive one unambiguous identity from a complete projection lease set."""

    encoded = projection_attempt_descriptor_json(leases)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"l2pa_{digest[:32]}"


def projection_attempt_descriptor_json(
    leases: Iterable[L2ProjectionLease],
) -> str:
    """Serialize the exact versioned member set for one projection attempt."""

    normalized = tuple(leases)
    if not normalized:
        raise ValueError("projection leases must not be empty")
    if any(not isinstance(lease, L2ProjectionLease) for lease in normalized):
        raise TypeError("projection lease must be an L2ProjectionLease")
    event_ids: set[str] = set()
    material: list[dict[str, Any]] = []
    for lease in sorted(normalized, key=lambda item: item.event_id):
        if lease.event_id in event_ids:
            raise ValueError("projection leases must contain unique event IDs")
        event_ids.add(lease.event_id)
        material.append(
            {
                "attempt_count": lease.attempt_count,
                "event_id": lease.event_id,
                "lease_token": lease.lease_token,
            }
        )
    return json.dumps(
        {
            "descriptor_version": PROJECTION_ATTEMPT_DESCRIPTOR_VERSION,
            "leases": material,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass(slots=True)
class L2BatchJob:
    """Lease-fenced extract queue payload built from durable projection rows."""

    job_id: str
    bucket_key: str
    events: list[dict[str, Any]]
    flush_reason: str
    estimated_tokens: int
    session_id: str | None = None
    user_id: str | None = None
    projection_leases: list[L2ProjectionLease] = field(default_factory=list)
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
            key=lambda item: (
                float(item.get("timestamp", 0.0) or 0.0),
                str(item.get("event_id", "")),
            ),
        )
        if not self.events:
            raise ValueError("events must not be empty")
        if any(not isinstance(lease, L2ProjectionLease) for lease in self.projection_leases):
            raise TypeError("projection leases must be L2ProjectionLease values")
        lease_ids = [lease.event_id for lease in self.projection_leases]
        if len(lease_ids) != len(set(lease_ids)):
            raise ValueError("projection_leases must contain unique event IDs")
        event_ids = {
            str(item.get("event_id", "")).strip()
            for item in self.events
            if str(item.get("event_id", "")).strip()
        }
        if lease_ids and set(lease_ids) != event_ids:
            raise ValueError("projection leases must cover the complete event batch")
        timestamps = [float(item.get("timestamp", 0.0) or 0.0) for item in self.events]
        self.oldest_event_timestamp = float(self.oldest_event_timestamp or min(timestamps))
        self.newest_event_timestamp = float(self.newest_event_timestamp or max(timestamps))

    @property
    def event_ids(self) -> list[str]:
        return [
            str(item.get("event_id", "")).strip()
            for item in self.events
            if str(item.get("event_id", "")).strip()
        ]

    @property
    def attempt_key(self) -> str:
        """Return the stable identity of this exact lease-fenced batch attempt."""

        if not self.projection_leases:
            return f"direct:{self.job_id}"
        return derive_projection_attempt_key(self.projection_leases)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event_ids"] = self.event_ids
        return payload


@dataclass(slots=True)
class L2PendingBatchBucket:
    """Process-local batch assembled from claimed durable projection rows."""

    bucket_key: str
    session_id: str | None = None
    user_id: str | None = None
    max_events: int | None = None
    max_estimated_tokens: int | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    projection_leases: list[L2ProjectionLease] = field(default_factory=list)
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
        if any(not isinstance(lease, L2ProjectionLease) for lease in self.projection_leases):
            raise TypeError("projection leases must be L2ProjectionLease values")
        if self.events:
            enqueued_at = float(self.created_at or self.last_event_at or _current_time())
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
        source_type: str | None = None,
        owner_key: str | None = None,
        max_events: int | None = None,
        max_estimated_tokens: int | None = None,
    ) -> "L2PendingBatchBucket":
        bucket_key = build_l2_batch_bucket_key(
            session_id=session_id,
            user_id=user_id,
            source_type=source_type,
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
        projection_lease: L2ProjectionLease | None = None,
    ) -> None:
        payload = dict(event)
        event_id = _non_empty_text(str(payload.get("event_id", "")), field_name="event_id")
        timestamp = float(payload.get("timestamp", 0.0) or 0.0)
        enqueued_at = float(_current_time() if queued_at is None else queued_at)
        payload["event_id"] = event_id
        payload["timestamp"] = timestamp
        self.events.append(payload)
        if projection_lease is not None:
            if projection_lease.event_id != event_id:
                raise ValueError("projection lease event_id must match the event")
            self.projection_leases.append(projection_lease)
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
        resolved_job_id = (
            _optional_text(job_id) or f"{self.bucket_key}:{int(self.newest_event_timestamp * 1000)}"
        )
        return L2BatchJob(
            job_id=resolved_job_id,
            bucket_key=self.bucket_key,
            events=self.events,
            flush_reason=flush_reason,
            estimated_tokens=self.estimated_tokens,
            session_id=self.session_id,
            user_id=self.user_id,
            projection_leases=list(self.projection_leases),
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
        normalized = sorted(
            {_non_empty_text(entity_id, field_name="entity_id") for entity_id in self.entity_ids}
        )
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
        normalized = sorted(
            {_non_empty_text(entity_id, field_name="entity_id") for entity_id in self.entity_ids}
        )
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


__all__ = [
    "PROJECTION_ATTEMPT_DESCRIPTOR_VERSION",
    "build_l2_batch_bucket_key",
    "derive_projection_attempt_key",
    "projection_attempt_descriptor_json",
    "L2BatchEvent",
    "L2BatchJob",
    "L2EntityReconcileJob",
    "L2EventWindow",
    "L2EventWindowSummary",
    "L2HistoryContext",
    "L2PendingBatchBucket",
    "L2ProjectionLease",
    "L2SnapshotRefreshJob",
    "ManualL2EventRequest",
]
