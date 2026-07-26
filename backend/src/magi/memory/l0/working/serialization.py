"""Serialization helpers for L0 working-memory checkpoints."""

from __future__ import annotations

import json
from typing import Any

import aiosqlite


def encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def decode_source_event_ids(value: Any) -> tuple[str, ...] | None:
    """Decode provenance without accepting malformed or ambiguous shapes."""
    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, (list, tuple, set)):
        return None
    if any(not isinstance(event_id, str) or not event_id.strip() for event_id in parsed):
        return None
    return tuple(dict.fromkeys(event_id.strip() for event_id in parsed))


def row_to_session(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "session_id": str(row["session_id"]),
        "user_id": row["user_id"],
        "runtime_agent_id": row["runtime_agent_id"],
        "status": str(row["status"]),
        "started_at": float(row["started_at"]),
        "last_active_at": float(row["last_active_at"]),
        "last_checkpoint_at": (
            float(row["last_checkpoint_at"]) if row["last_checkpoint_at"] else None
        ),
        "metadata": json.loads(row["metadata"] or "{}"),
    }

def row_to_goal(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "goal_id": str(row["goal_id"]),
        "parent_goal_id": row["parent_goal_id"],
        "goal_type": str(row["goal_type"]),
        "description": str(row["description"]),
        "status": str(row["status"]),
        "priority": int(row["priority"]),
        "created_at": float(row["created_at"]),
        "started_at": float(row["started_at"]) if row["started_at"] else None,
        "completed_at": float(row["completed_at"]) if row["completed_at"] else None,
        "result_summary": row["result_summary"],
        "metadata": json.loads(row["metadata"] or "{}"),
    }


def active_entity_key(row: aiosqlite.Row) -> tuple[str, str]:
    return str(row["entity_id"]), str(row["entity_type"])


def row_to_active_entity(row: aiosqlite.Row) -> dict[str, Any]:
    source_event_ids = decode_source_event_ids(row["source_event_ids"])
    return {
        "entity_id": str(row["entity_id"]),
        "entity_type": str(row["entity_type"]),
        "relevance_score": float(row["relevance_score"]),
        "snapshot": json.loads(row["snapshot_json"] or "{}"),
        # ``None`` deliberately survives decoding so the governance filter can
        # fail closed instead of treating malformed provenance as source-free.
        "source_event_ids": list(source_event_ids) if source_event_ids is not None else None,
        "loaded_at": float(row["loaded_at"]),
        "last_accessed_at": float(row["last_accessed_at"]),
        "access_count": int(row["access_count"]),
    }


def row_to_tactic(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "tactic_id": str(row["tactic_id"]),
        "scope_type": str(row["scope_type"]),
        "scope_id": str(row["scope_id"]),
        "tactic_type": str(row["tactic_type"]),
        "tactic_payload": json.loads(row["tactic_payload"] or "{}"),
        "source_event_ids": json.loads(row["source_event_ids"] or "[]"),
        "expires_at": float(row["expires_at"]) if row["expires_at"] else None,
        "created_at": float(row["created_at"]),
    }
