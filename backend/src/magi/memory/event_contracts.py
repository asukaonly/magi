"""Normalized contracts for the next-generation memory system."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional

from ..events.events import Event, EventTypes


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

    L0_ONLY = 1
    L1_ONLY = 2
    L0_AND_L1 = 3

    @property
    def includes_l1(self) -> bool:
        return self in {IngestTarget.L1_ONLY, IngestTarget.L0_AND_L1}

    @classmethod
    def _labels(cls) -> dict["IngestTarget", str]:
        return {
            IngestTarget.L0_ONLY: "l0_only",
            IngestTarget.L1_ONLY: "l1_only",
            IngestTarget.L0_AND_L1: "l0_and_l1",
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
    idempotency_key: Optional[str] = None
    media_path: Optional[str] = None
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
            "user_id": self.user_id,
            "task_id": self.task_id,
            "content": self.content,
            "author_type": self.author_type,
            "content_type": self.content_type,
            "importance_score": self.importance_score,
            "level": self.level,
            "media_path": self.media_path,
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
    session_id = _first_non_empty(payload.get("session_id"), payload_tags.get("session_id"), metadata.get("session_id"))
    turn_id = _first_non_empty(payload.get("turn_id"), metadata.get("turn_id"))
    user_id = _first_non_empty(payload.get("user_id"), payload_tags.get("user_id"), metadata.get("user_id"))
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
        return _first_non_empty(payload.get("message"), payload.get("status"), payload.get("node_type")) or ""
    return _first_non_empty(payload.get("summary"), payload.get("title"), payload.get("value")) or ""


def _resolve_source_item_id(event: Event, *, payload: dict[str, Any], metadata: dict[str, Any]) -> Optional[str]:
    if str(event.type) == EventTypes.ACTION_EXECUTED:
        return _first_non_empty(payload.get("action_type"), payload.get("source_item_id"), metadata.get("source_item_id"))
    return _first_non_empty(payload.get("source_item_id"), metadata.get("source_item_id"))


def _resolve_author_type(event: Event, *, payload: dict[str, Any], metadata: dict[str, Any]) -> str:
    author_type = _first_non_empty(payload.get("author_type"), metadata.get("author_type"))
    if author_type is not None:
        return author_type
    event_type = str(event.type)
    source = str(event.source or "").strip().lower()
    rule = _classify_event(event)
    if event_type == EventTypes.USER_MESSAGE:
        return "user"
    if event_type == EventTypes.AI_RESPONSE:
        return "assistant"
    if event_type == EventTypes.ACTION_EXECUTED:
        return "tool"
    if rule["memory_domain"] == MemoryDomain.RUNTIME_TELEMETRY or source == "system":
        return "system"
    if source in {"sensor", "location"}:
        return "sensor"
    return "external"


def _resolve_content_type(event: Event, *, payload: dict[str, Any], metadata: dict[str, Any]) -> str:
    content_type = _first_non_empty(payload.get("content_type"), metadata.get("content_type"))
    if content_type is not None:
        return content_type
    event_type = str(event.type)
    if event_type in {EventTypes.USER_MESSAGE, EventTypes.AI_RESPONSE}:
        return "text"
    if event_type == EventTypes.ACTION_EXECUTED:
        return "tool_result"
    if event_type in TRACE_RUNTIME_EVENT_TYPES:
        return "observation"
    return "text"


def _classify_event(event: Event) -> Dict[str, Any]:
    event_type = str(event.type)
    source = str(event.source or "")
    metadata = event.metadata if isinstance(event.metadata, dict) else {}

    if event_type == EventTypes.USER_MESSAGE:
        return {
            "memory_domain": MemoryDomain.USER_AUTHORED,
            "ingest_target": IngestTarget.L1_ONLY,
            "cognition_eligible": True,
            "tom_depth": TomDepth.DEFENSIVE_PSYCHOLOGY,
            "retention_class": RetentionClass.PERMANENT,
            "importance": 0.8,
        }

    if event_type in {"WORKER_AGENT_PROGRESS", EventTypes.LOOP_STARTED, EventTypes.LOOP_PHASE_STARTED, "Heartbeat"}:
        return {
            "memory_domain": MemoryDomain.RUNTIME_TELEMETRY if event_type == "WORKER_AGENT_PROGRESS" else MemoryDomain.SYSTEM_CONTROL,
            "ingest_target": IngestTarget.L0_ONLY,
            "cognition_eligible": False,
            "tom_depth": TomDepth.NONE,
            "retention_class": RetentionClass.DISPOSABLE,
            "importance": 0.1,
        }

    if event_type in TRACE_RUNTIME_EVENT_TYPES:
        return {
            "memory_domain": MemoryDomain.RUNTIME_TELEMETRY,
            "ingest_target": IngestTarget.L0_ONLY,
            "cognition_eligible": False,
            "tom_depth": TomDepth.NONE,
            "retention_class": RetentionClass.DISPOSABLE,
            "importance": 0.1,
        }

    if event_type in {EventTypes.TASK_ASSIGNED, EventTypes.TASK_STARTED, EventTypes.TASK_COMPLETED, EventTypes.TASK_FAILED}:
        return {
            "memory_domain": MemoryDomain.RUNTIME_TELEMETRY,
            "ingest_target": IngestTarget.L0_AND_L1,
            "cognition_eligible": False,
            "tom_depth": TomDepth.NONE,
            "retention_class": RetentionClass.COMPRESSIBLE,
            "importance": 0.6 if event_type in {EventTypes.TASK_ASSIGNED, EventTypes.TASK_STARTED} else 0.7,
        }

    if event_type == EventTypes.ERROR_OCCURRED:
        return {
            "memory_domain": MemoryDomain.RUNTIME_TELEMETRY,
            "ingest_target": IngestTarget.L1_ONLY,
            "cognition_eligible": False,
            "tom_depth": TomDepth.NONE,
            "retention_class": RetentionClass.COMPRESSIBLE,
            "importance": 0.9,
        }

    if event_type == EventTypes.ACTION_EXECUTED:
        return {
            "memory_domain": MemoryDomain.RUNTIME_TELEMETRY,
            "ingest_target": IngestTarget.L0_ONLY,
            "cognition_eligible": False,
            "tom_depth": TomDepth.NONE,
            "retention_class": RetentionClass.DISPOSABLE,
            "importance": 0.1,
        }

    # SENSOR_EVENT is normally routed by SensorIngestionGateway with per-sensor
    # policy. This fallback handles edge cases where it reaches _classify_event.
    if event_type == "SENSOR_EVENT":
        return {
            "memory_domain": MemoryDomain.EXTERNAL_ACTIVITY,
            "ingest_target": IngestTarget.L1_ONLY,
            "cognition_eligible": True,
            "tom_depth": TomDepth.NONE,
            "retention_class": RetentionClass.COMPRESSIBLE,
            "importance": 0.5,
        }

    return {
        "memory_domain": MemoryDomain.EXTERNAL_ACTIVITY,
        "ingest_target": IngestTarget.L1_ONLY,
        "cognition_eligible": True,
        "tom_depth": TomDepth.NONE,
        "retention_class": RetentionClass.COMPRESSIBLE,
        "importance": 0.5,
    }


__all__ = [
    "IngestTarget",
    "MemoryDomain",
    "MemoryEvent",
    "RetentionClass",
    "TomDepth",
    "normalize_runtime_event",
]
