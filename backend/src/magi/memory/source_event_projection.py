"""Project source domain events into canonical memory events."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import time
from typing import Any, Optional, cast

from magi.events.domain_payloads import SourceEventEmitted
from magi.events.events import EventLevel
from magi.events.source_activity_snapshot import (
    ACTIVITY_SNAPSHOT_METADATA_KEY,
    build_source_activity_snapshot,
)
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID


def build_source_memory_event(
    payload: SourceEventEmitted,
    *,
    event_id: str,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
    trace_context: Optional[Any] = None,
) -> MemoryEvent:
    """Construct canonical MemoryEvent from a source SourceEventEmitted payload."""
    output = dict(payload.output_dict or {})
    metadata = dict(payload.metadata_dict or {})
    projection = dict(payload.projection_dict or {})
    policy_data = dict(payload.policy_dict or {})
    activity_snapshot = build_source_activity_snapshot(payload, event_id=event_id)
    content = _resolve_memory_content(projection, activity_snapshot)
    owner_user_id = payload.owner_user_id or DEFAULT_USER_ID
    metadata_json = _build_memory_metadata(
        payload=payload,
        output=output,
        metadata=metadata,
        projection=projection,
        policy_data=policy_data,
        activity_snapshot=activity_snapshot,
        content=content,
        owner_user_id=owner_user_id,
    )

    return MemoryEvent(
        event_id=event_id,
        correlation_id=correlation_id or event_id,
        timestamp=float(output.get("occurred_at", 0.0)),
        created_at=float(output.get("captured_at", time.time())),
        event_type=payload.memory_event_type or "SOURCE_EVENT",
        source=str(output.get("source_type", "")),
        source_item_id=output.get("source_item_id"),
        memory_domain=MemoryDomain.from_value(
            policy_data.get("memory_domain", "external_activity")
        ),
        ingest_target=IngestTarget.from_value(policy_data.get("ingest_target", "l1_only")),
        cognition_eligible=bool(policy_data.get("cognition_eligible", True)),
        tom_depth=TomDepth.from_value(policy_data.get("tom_depth", "none")),
        retention_class=RetentionClass.from_value(
            policy_data.get("retention_class", "compressible")
        ),
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


def _resolve_memory_content(
    projection: Mapping[str, Any],
    activity_snapshot: Mapping[str, Any],
) -> str:
    summary = projection.get("summary") or activity_snapshot.get("summary") or ""
    return cast(str, projection.get("content") or summary)


def _build_memory_metadata(
    *,
    payload: SourceEventEmitted,
    output: Mapping[str, Any],
    metadata: Mapping[str, Any],
    projection: Mapping[str, Any],
    policy_data: Mapping[str, Any],
    activity_snapshot: Mapping[str, Any],
    content: str,
    owner_user_id: str,
) -> dict[str, Any]:
    metadata_json: dict[str, Any] = dict(output.get("domain_payload") or {})
    metadata_json.update(dict(projection.get("metadata") or {}))
    _add_l2_batch_policy(metadata_json, payload.l2_batch_policy_dict or {})
    _add_activity_snapshot(metadata_json, activity_snapshot, content)
    _add_structured_hints(metadata_json, metadata)
    _add_policy_metadata(metadata_json, policy_data, output)
    metadata_json["memory_owner_user_id"] = owner_user_id
    return metadata_json


def _add_l2_batch_policy(
    metadata_json: MutableMapping[str, Any],
    batch_policy: Mapping[str, Any],
) -> None:
    if batch_policy.get("owner"):
        metadata_json["l2_batch_owner"] = str(batch_policy["owner"])
    if batch_policy.get("catch_up_owner"):
        metadata_json["l2_batch_catch_up_owner"] = str(batch_policy["catch_up_owner"])
    if batch_policy.get("max_events") is not None:
        metadata_json["l2_batch_max_events"] = int(batch_policy["max_events"])
    if batch_policy.get("min_ready_events") is not None:
        metadata_json["l2_batch_min_ready_events"] = int(batch_policy["min_ready_events"])
    if batch_policy.get("max_estimated_tokens") is not None:
        metadata_json["l2_batch_max_estimated_tokens"] = int(batch_policy["max_estimated_tokens"])
    if batch_policy.get("max_wait_seconds") is not None:
        metadata_json["l2_batch_max_wait_seconds"] = int(batch_policy["max_wait_seconds"])


def _add_activity_snapshot(
    metadata_json: MutableMapping[str, Any],
    activity_snapshot: Mapping[str, Any],
    content: str,
) -> None:
    activity_for_metadata = dict(activity_snapshot)
    if activity_for_metadata.get("summary") == content:
        activity_for_metadata.pop("summary", None)
    metadata_json[ACTIVITY_SNAPSHOT_METADATA_KEY] = activity_for_metadata
    if activity_snapshot.get("raw_payload_ref"):
        metadata_json["raw_payload_ref"] = activity_snapshot["raw_payload_ref"]
    if activity_snapshot.get("processing_status"):
        metadata_json["processing_status"] = dict(activity_snapshot["processing_status"])


def _add_structured_hints(
    metadata_json: MutableMapping[str, Any],
    metadata: Mapping[str, Any],
) -> None:
    entity_hints = metadata.get("entities") or []
    if entity_hints:
        metadata_json["structured_entity_hints"] = list(entity_hints)
    graph_hints = metadata.get("fact_hints") or []
    if graph_hints:
        metadata_json["structured_graph_hints"] = list(graph_hints)


def _add_policy_metadata(
    metadata_json: MutableMapping[str, Any],
    policy_data: Mapping[str, Any],
    output: Mapping[str, Any],
) -> None:
    if policy_data.get("allow_llm_extraction", True) is False:
        metadata_json["allow_llm_extraction"] = False

    promotion_threshold = int(policy_data.get("promotion_threshold") or 0)
    if promotion_threshold > 0:
        metadata_json["promotion_threshold"] = promotion_threshold

    promotion_override = str(output.get("promotion_override") or "").strip()
    if promotion_override:
        metadata_json["promotion_override"] = promotion_override
