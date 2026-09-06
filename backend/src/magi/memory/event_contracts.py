"""Normalized contracts for the next-generation memory system."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional

from ..events.events import Event, EventTypes
from ..events.recall_feedback import RECALL_FEEDBACK_INTERACTION_KIND


class _LabeledIntEnum(IntEnum):
    @property
    def label(self) -> str:
        return type(self)._labels()[self]

    @classmethod
    def from_value(cls, value: "_LabeledIntEnum | int | str") -> "_LabeledIntEnum":
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        normalized = str(value).strip().lower()
        if normalized.isdigit():
            return cls(int(normalized))
        try:
            return cls._labels_by_name()[normalized]
        except KeyError as exc:
            raise ValueError(f"Unsupported {cls.__name__}: {value}") from exc

    @classmethod
    def _labels(cls) -> dict["_LabeledIntEnum", str]:
        raise NotImplementedError

    @classmethod
    def _labels_by_name(cls) -> dict[str, "_LabeledIntEnum"]:
        return {label: item for item, label in cls._labels().items()}


class IngestTarget(_LabeledIntEnum):
    """Storage-efficient ingest routing target for memory events."""

    RUNTIME_ONLY = 1
    L1_ONLY = 2

    @property
    def includes_l1(self) -> bool:
        return self is IngestTarget.L1_ONLY

    @classmethod
    def _labels(cls) -> dict["IngestTarget", str]:
        return {
            IngestTarget.RUNTIME_ONLY: "runtime_only",
            IngestTarget.L1_ONLY: "l1_only",
        }


class MemoryDomain(_LabeledIntEnum):
    USER_AUTHORED = 1
    EXTERNAL_ACTIVITY = 2
    RUNTIME_TELEMETRY = 3
    SYSTEM_CONTROL = 4
    INTERACTION = 5

    @classmethod
    def _labels(cls) -> dict["MemoryDomain", str]:
        return {
            MemoryDomain.USER_AUTHORED: "user_authored",
            MemoryDomain.EXTERNAL_ACTIVITY: "external_activity",
            MemoryDomain.RUNTIME_TELEMETRY: "runtime_telemetry",
            MemoryDomain.SYSTEM_CONTROL: "system_control",
            MemoryDomain.INTERACTION: "interaction",
        }


class TomDepth(_LabeledIntEnum):
    NONE = 1
    TOPOLOGY_ONLY = 2
    DEFENSIVE_PSYCHOLOGY = 3

    @classmethod
    def _labels(cls) -> dict["TomDepth", str]:
        return {
            TomDepth.NONE: "none",
            TomDepth.TOPOLOGY_ONLY: "topology_only",
            TomDepth.DEFENSIVE_PSYCHOLOGY: "defensive_psychology",
        }


class RetentionClass(_LabeledIntEnum):
    DISPOSABLE = 1
    COMPRESSIBLE = 2
    PERMANENT = 3

    @classmethod
    def _labels(cls) -> dict["RetentionClass", str]:
        return {
            RetentionClass.DISPOSABLE: "disposable",
            RetentionClass.COMPRESSIBLE: "compressible",
            RetentionClass.PERMANENT: "permanent",
        }


class AuthorType(_LabeledIntEnum):
    USER = 1
    ASSISTANT = 2
    TOOL = 3
    SYSTEM = 4
    SOURCE = 5
    EXTERNAL = 6
    UNKNOWN = 7

    @classmethod
    def _labels(cls) -> dict["AuthorType", str]:
        return {
            cls.USER: "user",
            cls.ASSISTANT: "assistant",
            cls.TOOL: "tool",
            cls.SYSTEM: "system",
            cls.SOURCE: "source",
            cls.EXTERNAL: "external",
            cls.UNKNOWN: "unknown",
        }


class ContentType(_LabeledIntEnum):
    TEXT = 1
    TOOL_RESULT = 2
    OBSERVATION = 3
    UNKNOWN = 4
    RUNTIME_DERIVATION = 5

    @classmethod
    def _labels(cls) -> dict["ContentType", str]:
        return {
            cls.TEXT: "text",
            cls.TOOL_RESULT: "tool_result",
            cls.OBSERVATION: "observation",
            cls.UNKNOWN: "unknown",
            cls.RUNTIME_DERIVATION: "runtime_derivation",
        }


def author_type_code(value: AuthorType | int | str | None) -> int:
    if value is None:
        return int(AuthorType.UNKNOWN)
    return int(AuthorType.from_value(value))


def author_type_label(value: AuthorType | int | str | None) -> str:
    if value is None:
        return AuthorType.UNKNOWN.label
    return AuthorType.from_value(value).label


def content_type_code(value: ContentType | int | str | None) -> int:
    if value is None:
        return int(ContentType.UNKNOWN)
    return int(ContentType.from_value(value))


def content_type_label(value: ContentType | int | str | None) -> str:
    if value is None:
        return ContentType.UNKNOWN.label
    return ContentType.from_value(value).label


TRACE_RUNTIME_EVENT_TYPES = {
    "CHAT_TOOL_LOOP_STEP",
    "TOOL_INTERACTION",
    "TOOL_INVOKED",
    "TURN_TRACE_STARTED",
    "TURN_TRACE_COMPLETED",
    "TURN_TRACE_FAILED",
    "TRACE_NODE_STARTED",
    "TRACE_NODE_COMPLETED",
    "TRACE_NODE_FAILED",
}


def generate_event_id(*, prefix: str = "evt") -> str:
    """Generate a stable external event id."""
    normalized_prefix = str(prefix or "evt").strip() or "evt"
    return f"{normalized_prefix}_{uuid.uuid4().hex}"


@dataclass(slots=True)
class MemoryEvent:
    """Canonical memory event used by the memory rewrite."""

    event_id: str
    correlation_id: str
    timestamp: float
    created_at: float
    event_type: str
    source: str
    source_item_id: Optional[str]
    memory_domain: MemoryDomain
    ingest_target: IngestTarget
    cognition_eligible: bool
    tom_depth: TomDepth
    retention_class: RetentionClass
    session_id: Optional[str]
    turn_id: Optional[str]
    user_id: Optional[str]
    task_id: Optional[str]
    content: str
    author_type: str
    content_type: str
    importance_score: float
    level: int
    id: Optional[int] = None
    session_seq: Optional[int] = None
    idempotency_key: Optional[str] = None
    media_path: Optional[str] = None
    # Capture-time full text pinned for L2 (RFC #56 P3). Transient: NOT a
    # fact_events column and NOT placed in metadata_json — the L1 write path
    # persists it to the l1_event_payload satellite, keeping the row lean.
    pinned_payload: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    embedding_status: Optional[str] = None
    embedding_profile_id: Optional[str] = None
    causation_id: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "created_at": self.created_at,
            "event_type": self.event_type,
            "source": self.source,
            "source_item_id": self.source_item_id,
            "idempotency_key": self.idempotency_key,
            "memory_domain": self.memory_domain.label,
            "ingest_target": self.ingest_target.label,
            "cognition_eligible": self.cognition_eligible,
            "tom_depth": self.tom_depth.label,
            "retention_class": self.retention_class.label,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "session_seq": self.session_seq,
            "user_id": self.user_id,
            "task_id": self.task_id,
            "content": self.content,
            "author_type": self.author_type,
            "content_type": self.content_type,
            "importance_score": self.importance_score,
            "level": self.level,
            "media_path": self.media_path,
            "pinned_payload": self.pinned_payload,
            "metadata_json": dict(self.metadata_json) if self.metadata_json is not None else None,
            "embedding_status": self.embedding_status,
            "embedding_profile_id": self.embedding_profile_id,
            "causation_id": self.causation_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
        }


def normalize_runtime_event(
    event: Event,
    *,
    event_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    parent_event_id: Optional[str] = None,
) -> MemoryEvent:
    """Normalize runtime events into the canonical memory contract."""

    now = time.time()
    payload = event.data if isinstance(event.data, dict) else {"value": event.data}
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    rule = _classify_event(event)
    level_value = event.level.value if hasattr(event.level, "value") else int(event.level)

    task_id = _first_non_empty(payload.get("task_id"), metadata.get("task_id"))
    payload_tags = payload.get("tags") if isinstance(payload.get("tags"), dict) else {}
    session_id = _first_non_empty(
        payload.get("session_id"), payload_tags.get("session_id"), metadata.get("session_id")
    )
    turn_id = _first_non_empty(payload.get("turn_id"), metadata.get("turn_id"))
    user_id = _first_non_empty(
        payload.get("user_id"), payload_tags.get("user_id"), metadata.get("user_id")
    )
    source_item_id = _resolve_source_item_id(event, payload=payload, metadata=metadata)
    normalized_idempotency_key = _first_non_empty(
        idempotency_key,
        payload.get("idempotency_key"),
        metadata.get("idempotency_key"),
    )

    resolved_event_id = event.event_id or event_id or generate_event_id()
    tc = event.trace_context

    return MemoryEvent(
        event_id=str(resolved_event_id),
        correlation_id=str(event.correlation_id or ""),
        timestamp=float(event.timestamp),
        created_at=now,
        event_type=str(event.type),
        source=str(event.source or "unknown"),
        source_item_id=source_item_id,
        memory_domain=rule["memory_domain"],
        ingest_target=rule["ingest_target"],
        cognition_eligible=bool(rule["cognition_eligible"]),
        tom_depth=rule["tom_depth"],
        retention_class=rule["retention_class"],
        session_id=session_id,
        turn_id=turn_id,
        user_id=user_id,
        task_id=task_id,
        content=_extract_content(event, payload=payload, metadata=metadata),
        author_type=_resolve_author_type(event, payload=payload, metadata=metadata),
        content_type=_resolve_content_type(event, payload=payload, metadata=metadata),
        importance_score=float(rule["importance"]),
        level=int(level_value),
        idempotency_key=normalized_idempotency_key,
        media_path=_first_non_empty(payload.get("media_path"), metadata.get("media_path")),
        causation_id=event.causation_id or parent_event_id,
        trace_id=tc.trace_id if tc else None,
        span_id=tc.span_id if tc else None,
        parent_span_id=tc.parent_span_id if tc else None,
    )


def _first_non_empty(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _extract_content(event: Event, *, payload: dict[str, Any], metadata: dict[str, Any]) -> str:
    event_type = str(event.type)
    content = _first_non_empty(payload.get("content"))
    if content is not None:
        return content
    if event_type == EventTypes.ACTION_EXECUTED:
        return _first_non_empty(payload.get("optimized_prompt"), payload.get("action_type")) or ""
    if event_type in TRACE_RUNTIME_EVENT_TYPES:
        return (
            _first_non_empty(
                payload.get("message"), payload.get("status"), payload.get("node_type")
            )
            or ""
        )
    return (
        _first_non_empty(payload.get("summary"), payload.get("title"), payload.get("value")) or ""
    )


def _resolve_source_item_id(
    event: Event, *, payload: dict[str, Any], metadata: dict[str, Any]
) -> Optional[str]:
    if str(event.type) == EventTypes.ACTION_EXECUTED:
        return _first_non_empty(
            payload.get("action_type"),
            payload.get("source_item_id"),
            metadata.get("source_item_id"),
        )
    return _first_non_empty(payload.get("source_item_id"), metadata.get("source_item_id"))


def _resolve_author_type(event: Event, *, payload: dict[str, Any], metadata: dict[str, Any]) -> str:
    # Runtime emits the assistant's own chat reply as an ActionExecuted event
    # wrapping a ChatResponseAction. Upstream emitters label it ``tool`` because
    # it travels through the action loop, but for evidence governance and
    # conversation retrieval it is assistant-authored. Detect and override
    # here so the classifier and downstream consumers see a single coherent
    # ``(assistant, runtime_derivation)`` shape instead of having every
    # consumer re-match on event_type + source + source_item_id.
    if _is_runtime_chat_response(event, payload):
        return AuthorType.ASSISTANT.label
    author_type = _first_non_empty(payload.get("author_type"), metadata.get("author_type"))
    if author_type is not None:
        return author_type_label(author_type)
    event_type = str(event.type)
    source = str(event.source or "").strip().lower()
    rule = _classify_event(event)
    if event_type == EventTypes.USER_MESSAGE:
        return AuthorType.USER.label
    if event_type == EventTypes.AI_RESPONSE:
        return AuthorType.ASSISTANT.label
    if event_type == EventTypes.ACTION_EXECUTED:
        return AuthorType.TOOL.label
    if rule["memory_domain"] == MemoryDomain.RUNTIME_TELEMETRY or source == "system":
        return AuthorType.SYSTEM.label
    if source in {"source", "location"}:
        return AuthorType.SOURCE.label
    return AuthorType.EXTERNAL.label


def _resolve_content_type(
    event: Event, *, payload: dict[str, Any], metadata: dict[str, Any]
) -> str:
    if _is_runtime_chat_response(event, payload):
        return ContentType.RUNTIME_DERIVATION.label
    content_type = _first_non_empty(payload.get("content_type"), metadata.get("content_type"))
    if content_type is not None:
        return content_type_label(content_type)
    event_type = str(event.type)
    if event_type in {EventTypes.USER_MESSAGE, EventTypes.AI_RESPONSE}:
        return ContentType.TEXT.label
    if event_type == EventTypes.ACTION_EXECUTED:
        return ContentType.TOOL_RESULT.label
    if event_type in TRACE_RUNTIME_EVENT_TYPES:
        return ContentType.OBSERVATION.label
    return ContentType.TEXT.label


def _is_runtime_chat_response(event: Event, payload: dict[str, Any]) -> bool:
    """Return True when the event is an ActionExecuted wrapping a ChatResponseAction.

    The runtime event emitter wraps the assistant's chat reply as an
    ``ActionExecuted`` event with ``action_type=ChatResponseAction`` so that
    it shares the same action-loop telemetry plumbing as tool executions.
    For evidence governance and L1 conversation retrieval the durable shape
    is assistant authored, not tool, so normalize promotes it before any
    downstream consumer.
    """
    if str(event.type).strip() != EventTypes.ACTION_EXECUTED:
        return False
    if str(event.source or "").strip().lower() != "runtime_event_emitter":
        return False
    action_type = payload.get("action_type") if isinstance(payload, dict) else None
    return str(action_type or "").strip().lower() == "chatresponseaction"


def _classify_event(event: Event) -> Dict[str, Any]:
    event_type = str(event.type)

    if event_type == EventTypes.USER_MESSAGE and _is_user_interaction_event(event):
        return _classification(
            memory_domain=MemoryDomain.INTERACTION,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=False,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.PERMANENT,
            importance=0.6,
        )

    if event_type == EventTypes.USER_MESSAGE:
        return _classification(
            memory_domain=MemoryDomain.USER_AUTHORED,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=True,
            tom_depth=TomDepth.DEFENSIVE_PSYCHOLOGY,
            retention_class=RetentionClass.PERMANENT,
            importance=0.8,
        )

    if _is_loop_control_event(event_type):
        return _loop_control_classification(event_type)

    if event_type in TRACE_RUNTIME_EVENT_TYPES:
        return _runtime_disposable_classification()

    if _is_task_lifecycle_event(event_type):
        return _task_lifecycle_classification(event_type)

    if event_type == EventTypes.ERROR_OCCURRED:
        return _classification(
            memory_domain=MemoryDomain.RUNTIME_TELEMETRY,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=False,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.COMPRESSIBLE,
            importance=0.9,
        )

    if event_type == EventTypes.ACTION_EXECUTED:
        return _runtime_disposable_classification()

    # SOURCE_EVENT is normally routed by SourceIngestionGateway with per-source
    # policy. This fallback handles edge cases where it reaches _classify_event.
    if event_type == "SOURCE_EVENT":
        return _external_activity_classification()

    return _external_activity_classification()


def _is_user_interaction_event(event: Event) -> bool:
    payload = event.data if isinstance(event.data, dict) else {}
    interaction_kind = str(payload.get("interaction_kind") or "").strip().lower()
    return interaction_kind in {RECALL_FEEDBACK_INTERACTION_KIND}


def _classification(
    *,
    memory_domain: MemoryDomain,
    ingest_target: IngestTarget,
    cognition_eligible: bool,
    tom_depth: TomDepth,
    retention_class: RetentionClass,
    importance: float,
) -> Dict[str, Any]:
    return {
        "memory_domain": memory_domain,
        "ingest_target": ingest_target,
        "cognition_eligible": cognition_eligible,
        "tom_depth": tom_depth,
        "retention_class": retention_class,
        "importance": importance,
    }


def _is_loop_control_event(event_type: str) -> bool:
    return event_type in {
        EventTypes.LOOP_STARTED,
        EventTypes.LOOP_PHASE_STARTED,
        "Heartbeat",
    }


def _loop_control_classification(event_type: str) -> Dict[str, Any]:
    return _classification(
        memory_domain=MemoryDomain.SYSTEM_CONTROL,
        ingest_target=IngestTarget.RUNTIME_ONLY,
        cognition_eligible=False,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.DISPOSABLE,
        importance=0.1,
    )


def _runtime_disposable_classification() -> Dict[str, Any]:
    return _classification(
        memory_domain=MemoryDomain.RUNTIME_TELEMETRY,
        ingest_target=IngestTarget.RUNTIME_ONLY,
        cognition_eligible=False,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.DISPOSABLE,
        importance=0.1,
    )


def _is_task_lifecycle_event(event_type: str) -> bool:
    return event_type in {
        EventTypes.TASK_ASSIGNED,
        EventTypes.TASK_STARTED,
        EventTypes.TASK_COMPLETED,
        EventTypes.TASK_FAILED,
    }


def _task_lifecycle_classification(event_type: str) -> Dict[str, Any]:
    return _classification(
        memory_domain=MemoryDomain.RUNTIME_TELEMETRY,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=False,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.COMPRESSIBLE,
        importance=(
            0.6 if event_type in {EventTypes.TASK_ASSIGNED, EventTypes.TASK_STARTED} else 0.7
        ),
    )


def _external_activity_classification() -> Dict[str, Any]:
    return _classification(
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.COMPRESSIBLE,
        importance=0.5,
    )


__all__ = [
    "AuthorType",
    "ContentType",
    "author_type_code",
    "author_type_label",
    "content_type_code",
    "content_type_label",
    "IngestTarget",
    "MemoryDomain",
    "MemoryEvent",
    "RetentionClass",
    "TomDepth",
    "normalize_runtime_event",
]
