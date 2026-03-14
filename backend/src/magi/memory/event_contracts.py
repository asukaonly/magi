"""Normalized contracts for the next-generation memory system."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..events.events import Event, EventTypes


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
    memory_domain: str
    ingest_target: str
    cognition_eligible: bool
    tom_depth: str
    retention_class: str
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
            "memory_domain": self.memory_domain,
            "ingest_target": self.ingest_target,
            "cognition_eligible": self.cognition_eligible,
            "tom_depth": self.tom_depth,
            "retention_class": self.retention_class,
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
        metadata=json.dumps(metadata, ensure_ascii=False),
        importance_score=float(rule["importance"]),
        importance_t0_base=float(rule["importance"]),
        importance_t1_score=None,
        importance_version=1,
        level=int(level_value),
        media_path=metadata.get("media_path"),
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


def _classify_event(event: Event) -> Dict[str, Any]:
    event_type = str(event.type)
    source = str(event.source or "")
    metadata = event.metadata if isinstance(event.metadata, dict) else {}

    if event_type == EventTypes.USER_MESSAGE:
        return {
            "memory_domain": "user_authored",
            "ingest_target": "l1_only",
            "cognition_eligible": True,
            "tom_depth": "defensive_psychology",
            "retention_class": "permanent",
            "importance": 0.8,
        }

    if event_type == "TIMELINE_EVENT":
        timeline = metadata.get("timeline") if isinstance(metadata.get("timeline"), dict) else {}
        source_type = str(timeline.get("source_type") or source)
        if source_type == "manual_journal":
            tom_depth = "defensive_psychology"
            retention_class = "permanent"
            domain = "user_authored"
        else:
            tom_depth = "topology_only"
            retention_class = "compressible"
            domain = "external_activity"
        return {
            "memory_domain": domain,
            "ingest_target": "l1_only",
            "cognition_eligible": True,
            "tom_depth": tom_depth,
            "retention_class": retention_class,
            "importance": 0.75,
        }

    if event_type in {"WORKER_AGENT_PROGRESS", EventTypes.LOOP_STARTED, EventTypes.LOOP_PHASE_STARTED, "Heartbeat"}:
        return {
            "memory_domain": "runtime_telemetry" if event_type == "WORKER_AGENT_PROGRESS" else "system_control",
            "ingest_target": "l0_only",
            "cognition_eligible": False,
            "tom_depth": "none",
            "retention_class": "disposable",
            "importance": 0.1,
        }

    if event_type in {EventTypes.TASK_ASSIGNED, EventTypes.TASK_STARTED, EventTypes.TASK_COMPLETED, EventTypes.TASK_FAILED}:
        return {
            "memory_domain": "runtime_telemetry",
            "ingest_target": "l0_and_l1",
            "cognition_eligible": False,
            "tom_depth": "none",
            "retention_class": "compressible",
            "importance": 0.6 if event_type in {EventTypes.TASK_ASSIGNED, EventTypes.TASK_STARTED} else 0.7,
        }

    if event_type == EventTypes.ERROR_OCCURRED:
        return {
            "memory_domain": "runtime_telemetry",
            "ingest_target": "l1_only",
            "cognition_eligible": False,
            "tom_depth": "none",
            "retention_class": "compressible",
            "importance": 0.9,
        }

    if event_type == EventTypes.ACTION_EXECUTED:
        return {
            "memory_domain": "interaction",
            "ingest_target": "l1_only",
            "cognition_eligible": True,
            "tom_depth": "none",
            "retention_class": "compressible",
            "importance": 0.55,
        }

    return {
        "memory_domain": "external_activity",
        "ingest_target": "l1_only",
        "cognition_eligible": True,
        "tom_depth": "none",
        "retention_class": "compressible",
        "importance": 0.5,
    }


__all__ = ["MemoryEvent", "normalize_runtime_event"]
