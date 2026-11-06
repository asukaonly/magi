"""Portable persistence values and deterministic row normalization."""

from __future__ import annotations
import time
import uuid
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional, TypeVar


_EnumT = TypeVar("_EnumT", bound="_LabeledIntEnum")


class _LabeledIntEnum(IntEnum):
    @property
    def label(self) -> str:
        return type(self)._labels()[self]

    @classmethod
    def from_value(cls: type[_EnumT], value: "_LabeledIntEnum | int | str") -> _EnumT:
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
    def _labels(cls: type[_EnumT]) -> dict[_EnumT, str]:
        raise NotImplementedError

    @classmethod
    def _labels_by_name(cls: type[_EnumT]) -> dict[str, _EnumT]:
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
