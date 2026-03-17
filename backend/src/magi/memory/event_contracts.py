"""Normalized contracts for the next-generation memory system."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
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


@dataclass(slots=True)
class MemoryEvent:
    """Canonical memory event used by the memory rewrite."""

    event_id: str
    correlation_id: str
    parent_event_id: Optional[str]
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
    user_id: Optional[str]
    task_id: Optional[str]
    goal_id: Optional[str]
    raw_content: str
    structured_payload: str
    metadata: str
    importance_score: float
    importance_t0_base: float
    importance_t1_score: Optional[float]
    importance_version: int
    level: int
    media_path: Optional[str] = None
    entity_focus_hint: Optional[str] = None
    speaker_role: Optional[str] = None
    grounding_type: Optional[str] = None
    derived_from_event_ids: list[str] = field(default_factory=list)
    semantic_owner_hint: Optional[str] = None
    originality_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "parent_event_id": self.parent_event_id,
            "timestamp": self.timestamp,
            "created_at": self.created_at,
            "event_type": self.event_type,
            "source": self.source,
            "source_item_id": self.source_item_id,
            "memory_domain": self.memory_domain.label,
            "ingest_target": self.ingest_target.label,
            "cognition_eligible": self.cognition_eligible,
            "tom_depth": self.tom_depth.label,
            "retention_class": self.retention_class.label,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "raw_content": self.raw_content,
            "structured_payload": self.structured_payload,
            "metadata": self.metadata,
            "importance_score": self.importance_score,
            "importance_t0_base": self.importance_t0_base,
            "importance_t1_score": self.importance_t1_score,
            "importance_version": self.importance_version,
            "level": self.level,
            "media_path": self.media_path,
            "entity_focus_hint": self.entity_focus_hint,
            "speaker_role": self.speaker_role,
            "grounding_type": self.grounding_type,
            "derived_from_event_ids": list(self.derived_from_event_ids),
            "semantic_owner_hint": self.semantic_owner_hint,
            "originality_type": self.originality_type,
        }


def normalize_runtime_event(event: Event, *, event_id: Optional[str] = None, parent_event_id: Optional[str] = None) -> MemoryEvent:
    """Normalize runtime events into the new memory contract."""

    now = time.time()
    payload = event.data if isinstance(event.data, dict) else {"value": event.data}
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    rule = _classify_event(event)
    level_value = event.level.value if hasattr(event.level, "value") else int(event.level)

    task_id = _first_non_empty(payload.get("task_id"), metadata.get("task_id"))
    session_id = _first_non_empty(payload.get("session_id"), metadata.get("session_id"))
    user_id = _first_non_empty(payload.get("user_id"), metadata.get("user_id"))
    goal_id = _first_non_empty(payload.get("goal_id"), metadata.get("goal_id"))
    source_item_id = _first_non_empty(payload.get("source_item_id"), metadata.get("source_item_id"))
    entity_focus_hint = _first_non_empty(payload.get("entity_focus_hint"), metadata.get("entity_focus_hint"))
    evidence_metadata = _build_evidence_metadata(event, payload=payload, metadata=metadata)
    persisted_metadata = {
        **metadata,
        "speaker_role": evidence_metadata["speaker_role"],
        "grounding_type": evidence_metadata["grounding_type"],
        "derived_from_event_ids": evidence_metadata["derived_from_event_ids"],
        "semantic_owner_hint": evidence_metadata["semantic_owner_hint"],
        "originality_type": evidence_metadata["originality_type"],
    }

    return MemoryEvent(
        event_id=str(event_id or f"evt_{uuid.uuid4().hex}"),
        correlation_id=str(event.correlation_id or ""),
        parent_event_id=parent_event_id,
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
        user_id=user_id,
        task_id=task_id,
        goal_id=goal_id,
        raw_content=_build_raw_content(event),
        structured_payload=json.dumps(payload, ensure_ascii=False),
        metadata=json.dumps(persisted_metadata, ensure_ascii=False),
        importance_score=float(rule["importance"]),
        importance_t0_base=float(rule["importance"]),
        importance_t1_score=None,
        importance_version=1,
        level=int(level_value),
        media_path=metadata.get("media_path"),
        entity_focus_hint=entity_focus_hint,
        speaker_role=evidence_metadata["speaker_role"],
        grounding_type=evidence_metadata["grounding_type"],
        derived_from_event_ids=evidence_metadata["derived_from_event_ids"],
        semantic_owner_hint=evidence_metadata["semantic_owner_hint"],
        originality_type=evidence_metadata["originality_type"],
    )


def _first_non_empty(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _build_raw_content(event: Event) -> str:
    parts = [str(event.type)]
    payload = event.data if isinstance(event.data, dict) else {"value": event.data}
    for value in payload.values():
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    for value in metadata.values():
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts).strip()


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for item in value if (text := str(item).strip())]
    if isinstance(value, tuple):
        return [text for item in value if (text := str(item).strip())]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _build_evidence_metadata(event: Event, *, payload: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.type)
    source = str(event.source or "").strip().lower()
    rule = _classify_event(event)

    speaker_role = _first_non_empty(payload.get("speaker_role"), metadata.get("speaker_role"))
    if speaker_role is None:
        if event_type == EventTypes.USER_MESSAGE:
            speaker_role = "user"
        elif event_type == EventTypes.AI_RESPONSE:
            speaker_role = "assistant"
        elif event_type == "TIMELINE_EVENT":
            speaker_role = "timeline"
        elif rule["memory_domain"] == MemoryDomain.RUNTIME_TELEMETRY or source == "system":
            speaker_role = "system"
        elif source in {"sensor", "location"}:
            speaker_role = "sensor"
        elif source in {"calendar", "timeline", "external_feed"}:
            speaker_role = "external"

    derived_from_event_ids = _normalize_string_list(
        payload.get("derived_from_event_ids", metadata.get("derived_from_event_ids"))
    )

    grounding_type = _first_non_empty(payload.get("grounding_type"), metadata.get("grounding_type"))
    if grounding_type is None:
        if event_type == EventTypes.USER_MESSAGE:
            grounding_type = "self_reported"
        elif derived_from_event_ids:
            grounding_type = "quoted_from_history"
        elif metadata.get("tool_name") or metadata.get("tool_call_id") or metadata.get("tool_result_ref"):
            grounding_type = "tool_grounded"
        elif event_type == EventTypes.AI_RESPONSE:
            grounding_type = "freeform_generated"
        else:
            grounding_type = "observed"

    semantic_owner_hint = _first_non_empty(payload.get("semantic_owner_hint"), metadata.get("semantic_owner_hint"))
    if semantic_owner_hint is None:
        if speaker_role == "user":
            semantic_owner_hint = "user"
        elif grounding_type == "tool_grounded":
            semantic_owner_hint = "world"
        elif speaker_role in {"timeline", "sensor", "external", "system"}:
            semantic_owner_hint = "world"
        elif speaker_role == "assistant":
            semantic_owner_hint = "assistant"

    originality_type = _first_non_empty(payload.get("originality_type"), metadata.get("originality_type"))
    if originality_type is None:
        if derived_from_event_ids:
            originality_type = "quoted" if grounding_type == "quoted_from_history" else "derived"
        else:
            originality_type = "primary"

    return {
        "speaker_role": speaker_role,
        "grounding_type": grounding_type,
        "derived_from_event_ids": derived_from_event_ids,
        "semantic_owner_hint": semantic_owner_hint,
        "originality_type": originality_type,
    }


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

    if event_type == "TIMELINE_EVENT":
        timeline = metadata.get("timeline") if isinstance(metadata.get("timeline"), dict) else {}
        source_type = str(timeline.get("source_type") or source)
        if source_type == "manual_journal":
            tom_depth = TomDepth.DEFENSIVE_PSYCHOLOGY
            retention_class = RetentionClass.PERMANENT
            domain = MemoryDomain.USER_AUTHORED
        else:
            tom_depth = TomDepth.TOPOLOGY_ONLY
            retention_class = RetentionClass.COMPRESSIBLE
            domain = MemoryDomain.EXTERNAL_ACTIVITY
        return {
            "memory_domain": domain,
            "ingest_target": IngestTarget.L1_ONLY,
            "cognition_eligible": True,
            "tom_depth": tom_depth,
            "retention_class": retention_class,
            "importance": 0.75,
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
            "memory_domain": MemoryDomain.INTERACTION,
            "ingest_target": IngestTarget.L1_ONLY,
            "cognition_eligible": True,
            "tom_depth": TomDepth.NONE,
            "retention_class": RetentionClass.COMPRESSIBLE,
            "importance": 0.55,
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
