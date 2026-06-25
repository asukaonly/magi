"""Pure projection functions: SensorEventEmitted -> MemoryEvent / TimelineEvent dict.

Used by:
- MemoryIngestionSubscriber._from_sensor (memory ingest)
- TimelineSubscriber._on_event (timeline read model)

Replaces SensorIngestionGateway._build_memory_event by reading from the event
payload instead of holding sensor / output objects directly.
"""
from __future__ import annotations

import time
from typing import Any, Mapping, Optional

from magi.events.domain_payloads import SensorEventEmitted
from magi.events.events import EventLevel
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.runtime_defaults import DEFAULT_USER_ID


def build_timeline_event_dict(
    payload: SensorEventEmitted,
    *,
    event_id: str,
) -> Mapping[str, Any]:
    """Build the TimelineEvent dict shape from sensor payload context.

    Mirrors the existing build_sensor_timeline_event output structure (see
    awareness/sensor_projection.py) but reads from payload dicts.
    """
    output = payload.output_dict or {}
    metadata = payload.metadata_dict or {}
    projection = payload.projection_dict or {}
    extra_entities = metadata.get("entities") or []
    extra_tags = metadata.get("tags") or []
    domain_payload = output.get("domain_payload") or {}

    return {
        "event_id": event_id,
        "source_type": output.get("source_type", ""),
        "source_item_id": output.get("source_item_id", ""),
        "occurred_at": float(output.get("occurred_at", 0.0)),
        "captured_at": float(output.get("captured_at", 0.0)),
        "title": projection.get("title", ""),
        "summary": projection.get("summary", ""),
        "retention_mode": domain_payload.get("retention_mode", "analyze_only"),
        "raw_payload_ref": output.get("raw_payload_ref"),
        "content_blocks": list(output.get("content_blocks", [])),
        "entities": list(output.get("entities", [])) + list(extra_entities),
        "tags": list(dict.fromkeys(list(output.get("tags", [])) + list(extra_tags))),
        "privacy_labels": list(domain_payload.get("privacy_labels", [])),
        "processing_status": {
            "stored": True,
            "analyzed": bool(metadata.get("relation_candidates") or metadata.get("fact_hints")),
        },
        "provenance": dict(output.get("provenance") or {}),
    }


def build_sensor_memory_event(
    payload: SensorEventEmitted,
    *,
    event_id: str,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
    trace_context: Optional[Any] = None,
) -> MemoryEvent:
    """Construct canonical MemoryEvent from a sensor SensorEventEmitted payload."""
    output = payload.output_dict or {}
    metadata = payload.metadata_dict or {}
    projection = payload.projection_dict or {}
    policy_data = payload.policy_dict or {}

    timeline_event_dict = build_timeline_event_dict(payload, event_id=event_id)
    summary = projection.get("summary") or timeline_event_dict.get("summary") or ""
    content = projection.get("content") or summary

    metadata_json: dict[str, Any] = dict(output.get("domain_payload") or {})
    projection_metadata = dict(projection.get("metadata") or {})
    metadata_json.update(projection_metadata)

    if payload.l2_batch_policy_dict:
        bp = payload.l2_batch_policy_dict
        if bp.get("owner"):
            metadata_json["l2_batch_owner"] = str(bp["owner"])
        if bp.get("catch_up_owner"):
            metadata_json["l2_batch_catch_up_owner"] = str(bp["catch_up_owner"])
        if bp.get("max_events") is not None:
            metadata_json["l2_batch_max_events"] = int(bp["max_events"])
        if bp.get("min_ready_events") is not None:
            metadata_json["l2_batch_min_ready_events"] = int(bp["min_ready_events"])
        if bp.get("max_estimated_tokens") is not None:
            metadata_json["l2_batch_max_estimated_tokens"] = int(bp["max_estimated_tokens"])
        if bp.get("max_wait_seconds") is not None:
            metadata_json["l2_batch_max_wait_seconds"] = int(bp["max_wait_seconds"])

    # De-duplicate when timeline summary and L1 content match. For compact /
    # evidence-only presentations they intentionally differ: timeline.summary
    # stays short while event.content keeps the full searchable text.
    timeline_for_metadata = dict(timeline_event_dict)
    if timeline_for_metadata.get("summary") == content:
        timeline_for_metadata.pop("summary", None)
    metadata_json["timeline"] = timeline_for_metadata
    if timeline_event_dict.get("raw_payload_ref"):
        metadata_json["raw_payload_ref"] = timeline_event_dict["raw_payload_ref"]
    if timeline_event_dict.get("processing_status"):
        metadata_json["processing_status"] = dict(timeline_event_dict["processing_status"])

    entity_hints = metadata.get("entities") or []
    if entity_hints:
        metadata_json["structured_entity_hints"] = list(entity_hints)
    graph_hints = metadata.get("fact_hints") or []
    if graph_hints:
        metadata_json["structured_graph_hints"] = list(graph_hints)

    owner_user_id = payload.owner_user_id or DEFAULT_USER_ID
    metadata_json["memory_owner_user_id"] = owner_user_id

    # Structured-only mode: a sensor with allow_llm_extraction=False gets deterministic
    # direct-writes but no LLM phase1/2. Stored only when disabled to keep metadata_json
    # lean; L2 treats a missing key as "extraction allowed".
    if policy_data.get("allow_llm_extraction", True) is False:
        metadata_json["allow_llm_extraction"] = False
    # P2 frequency gate: threshold from policy; per-event promotion_key flows via
    # domain_payload (already merged into metadata_json above). Stored only when enabled.
    _promotion_threshold = int(policy_data.get("promotion_threshold") or 0)
    if _promotion_threshold > 0:
        metadata_json["promotion_threshold"] = _promotion_threshold
    # P4 escape hatch: a per-event promotion override (force_full / force_structured_only)
    # from the sensor output. Stored only when set so resolve_llm_extraction can honor it.
    _promotion_override = str(output.get("promotion_override") or "").strip()
    if _promotion_override:
        metadata_json["promotion_override"] = _promotion_override

    event_type = payload.memory_event_type or "SENSOR_EVENT"

    return MemoryEvent(
        event_id=event_id,
        correlation_id=correlation_id or event_id,
        timestamp=float(output.get("occurred_at", 0.0)),
        created_at=float(output.get("captured_at", time.time())),
        event_type=event_type,
        source=str(output.get("source_type", "")),
        source_item_id=output.get("source_item_id"),
        memory_domain=MemoryDomain.from_value(policy_data.get("memory_domain", "external_activity")),
        ingest_target=IngestTarget.from_value(policy_data.get("ingest_target", "l1_only")),
        cognition_eligible=bool(policy_data.get("cognition_eligible", True)),
        tom_depth=TomDepth.from_value(policy_data.get("tom_depth", "none")),
        retention_class=RetentionClass.from_value(policy_data.get("retention_class", "compressible")),
        session_id=None,
        turn_id=None,
        user_id=owner_user_id,
        task_id=None,
        content=content,
        author_type=str(policy_data.get("author_type", "external")),
        content_type=str(policy_data.get("content_type", "observation")),
        importance_score=float(policy_data.get("importance_bias", 0.5)),
        level=EventLevel.INFO.value,
        idempotency_key=payload.idempotency_key,
        media_path=output.get("raw_payload_ref"),
        pinned_payload=output.get("pinned_payload"),
        metadata_json=metadata_json or None,
        causation_id=causation_id,
        trace_id=getattr(trace_context, "trace_id", None) if trace_context else None,
        span_id=getattr(trace_context, "span_id", None) if trace_context else None,
        parent_span_id=getattr(trace_context, "parent_span_id", None) if trace_context else None,
    )
