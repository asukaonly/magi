"""Traceable source references and conservative filtering of retained evidence."""
from __future__ import annotations

import json
from typing import Any

from ...memory.hybrid_retrieval.models import RetrievalPayload
from ..source_store import source_object_identity


def event_metadata(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("metadata") or event.get("metadata_json") or {}
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


def event_source_ref(event: dict[str, Any]) -> dict[str, Any] | None:
    metadata = event_metadata(event)
    keys = ("source_connection_id", "source_id", "source_object_id", "source_object_version")
    if not all(isinstance(metadata.get(key), str) and metadata[key] for key in keys):
        return None
    return {
        "connection_id": metadata[keys[0]], "source_id": metadata[keys[1]],
        "object_id": metadata[keys[2]], "version": metadata[keys[3]],
        "identity": source_object_identity(metadata[keys[0]], metadata[keys[1]], metadata[keys[2]]),
        "event_id": event.get("event_id"), "source_type": event.get("source"),
        "thread_id": metadata.get("thread_id"),
    }


def restrict_payload(payload: RetrievalPayload, owners: set[tuple[str, str]], *, object_id: str = "", thread_id: str = "") -> RetrievalPayload:
    """A source restriction must never leak unproven derived or cross-account evidence."""
    events = [event for event in payload.l1_events if (ref := event_source_ref(event))
              and (ref["connection_id"], ref["source_id"]) in owners
              and (not object_id or ref["object_id"] == object_id)
              and (not thread_id or ref.get("thread_id") == thread_id)]
    allowed_events = {str(event.get("event_id")) for event in events if event.get("event_id")}
    result = RetrievalPayload(l1_events=events, trace=dict(payload.trace))
    # Only explicit, fully covered lineage can qualify a derived finding.
    for name in ("l2_assertions", "l2_relationships", "l2_episodes", "l2_experiences", "l3_reflections", "l4_procedures"):
        accepted = []
        for item in getattr(payload, name):
            lineage = item.get("source_event_ids") or []
            if lineage and set(lineage) <= allowed_events:
                accepted.append(item)
        setattr(result, name, accepted)
    result.trace["source_scope_applied"] = True
    return result


def annotate_local_findings(recall: dict[str, Any], payload: RetrievalPayload) -> None:
    refs = {str(event.get("event_id")): event_source_ref(event) for event in payload.l1_events}
    for finding in recall["findings"]:
        finding["origin"] = "memory"
        feedback = str(finding.get("feedback_ref") or "")
        event_id = feedback.removeprefix("event:") if feedback.startswith("event:") else None
        if event_id and refs.get(str(event_id)):
            finding["source_ref"] = refs[str(event_id)]


def merge_findings(retained: list[dict[str, Any]], live: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One source revision contributes once; live state preserves prior-version context."""
    observed = {item["source_ref"]["identity"]: item for item in live}
    result = []
    for item in retained:
        ref = item.get("source_ref") or {}
        current = observed.get(ref.get("identity"))
        if current is None:
            result.append(item)
        elif ref.get("version") != current["source_ref"]["version"]:
            current.setdefault("prior_versions", []).append(ref)
    return [*live, *result]
