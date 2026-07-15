"""Version snapshots and temporal state reconstruction for L2 relationships."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, Dict, List

import aiosqlite

from ..corrections.fingerprints import scope_specificity
from .common import L2RetrievalQueryHostProtocol


def _relationship_version_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    recorded_at = float(row.get("created_at") or 0.0)
    valid_from = _optional_float(row.get("valid_from"))
    valid_to = _optional_float(row.get("valid_to"))
    first_observed = _optional_float(row.get("first_observed_at"))
    last_observed = _optional_float(row.get("last_observed_at"))
    edge_created = _optional_float(row.get("edge_created_at"))
    provenance_times = [
        value
        for value in (first_observed, edge_created)
        if value is not None and value <= recorded_at
    ]
    inferred_start = min(provenance_times, default=recorded_at)
    return {
        "triple_id": str(row.get("triple_id") or ""),
        "subject_id": str(row.get("subject_id") or ""),
        "subject_type": str(row.get("subject_type") or ""),
        "predicate": str(row.get("predicate") or ""),
        "object_id": str(row.get("object_id") or ""),
        "object_type": str(row.get("object_type") or ""),
        "fact_kind": str(row.get("fact_kind") or ""),
        "confidence": float(row.get("confidence") or 0.0),
        "evidence_event_ids": _json_list(row.get("evidence_event_ids")),
        "evidence_text": str(row.get("evidence_text") or ""),
        "natural_summary": str(row.get("natural_summary") or ""),
        "observation_count": int(row.get("observation_count") or 1),
        "first_observed_at": valid_from if valid_from is not None else inferred_start,
        "last_observed_at": last_observed or valid_to or recorded_at,
        "last_confirmed_at": _optional_float(row.get("last_confirmed_at")),
        "source_type": str(row.get("source_type") or "version_history"),
        "extraction_method": str(row.get("extraction_method") or "explicit"),
        "embedding_status": "pending",
        "expires_at": _optional_float(row.get("expires_at")),
        "valid_from": valid_from,
        "valid_to": valid_to,
        "status": str(row.get("status") or ""),
        "status_reason": None,
        "deprecated_by": None,
        "deprecated_at": None,
        "evidence_class": row.get("evidence_class"),
        "slot_key": str(row.get("slot_key") or ""),
        "claim_fingerprint": str(row.get("claim_fingerprint") or ""),
        "authority_ref": row.get("authority_ref"),
        "scope_key": str(row.get("scope_key") or "global"),
        "scope": _json_object(row.get("scope_json")),
        "created_at": edge_created if edge_created is not None else inferred_start,
        "updated_at": recorded_at,
        "_governed_version_id": str(row.get("version_id") or ""),
        "_version_recorded_at": recorded_at,
    }


def _current_relationship_snapshot(
    host: L2RetrievalQueryHostProtocol,
    row: aiosqlite.Row,
) -> Dict[str, Any]:
    result = host._relation_row_to_dict(row)
    result["_governed_version_id"] = f"current:{result['triple_id']}"
    result["_version_recorded_at"] = float(result.get("updated_at") or time.time())
    return result


def _materialize_relationship_states(
    snapshots: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_triple: dict[str, List[Dict[str, Any]]] = {}
    for snapshot in snapshots:
        triple_id = str(snapshot.get("triple_id") or "")
        if triple_id:
            by_triple.setdefault(triple_id, []).append(snapshot)

    materialized: List[Dict[str, Any]] = []
    for triple_snapshots in by_triple.values():
        ordered = sorted(
            triple_snapshots,
            key=lambda item: (
                float(item.get("_version_recorded_at") or 0.0),
                str(item.get("_governed_version_id") or ""),
            ),
        )
        ordered = _deduplicate_snapshot_rows(ordered)
        states = _active_relationship_states(ordered)
        for index, state in enumerate(states):
            start = _state_start(states, index)
            end_candidates = [
                value
                for value in (
                    _optional_float(state["row"].get("valid_to")),
                    _state_closure_time(ordered, state),
                    _state_start(states, index + 1) if index + 1 < len(states) else None,
                )
                if value is not None
            ]
            end = min(end_candidates, default=None)
            if end is not None and end <= start:
                continue
            row = dict(state["row"])
            row["valid_from"] = start
            row["valid_to"] = end
            row["status"] = "active"
            materialized.append(row)
    return materialized


def _deduplicate_snapshot_rows(
    ordered: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    deduplicated: List[Dict[str, Any]] = []
    for snapshot in ordered:
        if deduplicated and _snapshot_payload_key(deduplicated[-1]) == _snapshot_payload_key(
            snapshot
        ):
            if str(snapshot.get("_governed_version_id") or "").startswith("current:"):
                replacement = dict(snapshot)
                replacement["_version_recorded_at"] = deduplicated[-1].get("_version_recorded_at")
                deduplicated[-1] = replacement
            continue
        deduplicated.append(snapshot)
    return deduplicated


def _snapshot_payload_key(snapshot: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        *_relationship_state_key(snapshot),
        snapshot.get("status"),
        snapshot.get("valid_from"),
        snapshot.get("valid_to"),
    )


def _relationship_state_key(snapshot: Mapping[str, Any]) -> tuple[Any, ...]:
    """Identify one immutable active payload, not only its logical claim."""
    return (
        snapshot.get("claim_fingerprint"),
        snapshot.get("scope_key"),
        snapshot.get("subject_id"),
        snapshot.get("predicate"),
        snapshot.get("object_id"),
        snapshot.get("confidence"),
        tuple(snapshot.get("evidence_event_ids") or []),
        snapshot.get("evidence_text"),
        snapshot.get("natural_summary"),
        snapshot.get("observation_count"),
        snapshot.get("first_observed_at"),
        snapshot.get("last_observed_at"),
        snapshot.get("last_confirmed_at"),
        snapshot.get("source_type"),
        snapshot.get("extraction_method"),
        snapshot.get("expires_at"),
        snapshot.get("evidence_class"),
        snapshot.get("authority_ref"),
    )


def _active_relationship_states(
    ordered: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    states: List[Dict[str, Any]] = []
    for index, snapshot in enumerate(ordered):
        if str(snapshot.get("status") or "") != "active":
            continue
        state_key = _relationship_state_key(snapshot)
        if states and states[-1]["key"] == state_key and int(states[-1]["last_index"]) == index - 1:
            states[-1]["row"] = snapshot
            states[-1]["last_index"] = index
            continue
        states.append(
            {
                "key": state_key,
                "row": snapshot,
                "first_index": index,
                "last_index": index,
                "first_recorded_at": float(snapshot.get("_version_recorded_at") or 0.0),
            }
        )
    return states


def _state_start(states: List[Dict[str, Any]], index: int) -> float:
    state = states[index]
    valid_from = _optional_float(state["row"].get("valid_from"))
    recorded_at = float(state["first_recorded_at"])
    if index == 0:
        if valid_from is not None:
            return valid_from
        provenance_times = [
            value
            for value in (
                _optional_float(state["row"].get("first_observed_at")),
                _optional_float(state["row"].get("created_at")),
            )
            if value is not None
        ]
        return min(provenance_times, default=recorded_at)
    previous_recorded_at = float(states[index - 1]["first_recorded_at"])
    if valid_from is not None and valid_from >= previous_recorded_at:
        return valid_from
    return recorded_at


def _state_closure_time(
    ordered: List[Dict[str, Any]],
    state: Mapping[str, Any],
) -> float | None:
    state_key = state["key"]
    for snapshot in ordered[int(state["last_index"]) + 1 :]:
        snapshot_key = _relationship_state_key(snapshot)
        if snapshot_key != state_key:
            continue
        valid_to = _optional_float(snapshot.get("valid_to"))
        if valid_to is not None:
            return valid_to
        if str(snapshot.get("status") or "") != "active":
            return float(snapshot.get("_version_recorded_at") or 0.0)
    return None


def _relationship_overlaps_request(
    relationship: Mapping[str, Any],
    *,
    effective_at: float,
    effective_range: tuple[float | None, float | None] | None,
) -> bool:
    valid_from = _optional_float(relationship.get("valid_from"))
    valid_to = _optional_float(relationship.get("valid_to"))
    expires_at = _optional_float(relationship.get("expires_at"))
    if effective_range is None:
        return (
            (valid_from is None or valid_from <= effective_at)
            and (valid_to is None or valid_to > effective_at)
            and (expires_at is None or expires_at > effective_at)
        )
    range_start, range_end = effective_range
    return (
        (range_end is None or valid_from is None or valid_from <= range_end)
        and (range_start is None or valid_to is None or valid_to > range_start)
        and (range_start is None or expires_at is None or expires_at > range_start)
    )


def _relationship_scope_priority(relationship: Mapping[str, Any]) -> tuple[int, float]:
    return (
        scope_specificity(relationship.get("scope")),
        float(relationship.get("updated_at") or 0.0),
    )


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _json_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


__all__ = [
    "_current_relationship_snapshot",
    "_materialize_relationship_states",
    "_relationship_overlaps_request",
    "_relationship_scope_priority",
    "_relationship_version_to_dict",
]
