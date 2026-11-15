"""Normalized contracts for the next-generation memory system."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..events.events import Event, EventTypes
from ..events.recall_feedback import RECALL_FEEDBACK_INTERACTION_KIND

from magi_plugin_sdk.storage_models.events import (
    _EnumT as _EnumT,
    _LabeledIntEnum as _LabeledIntEnum,
    IngestTarget,
    MemoryDomain,
    TomDepth,
    RetentionClass,
    AuthorType,
    ContentType,
    author_type_code,
    author_type_label,
    content_type_code,
    content_type_label,
    TRACE_RUNTIME_EVENT_TYPES,
    generate_event_id,
    MemoryEvent,
)

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
    raw_tags = payload.get("tags")
    payload_tags = raw_tags if isinstance(raw_tags, dict) else {}
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
