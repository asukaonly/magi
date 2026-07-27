"""Serialization helpers for L0 attention checkpoints."""

from __future__ import annotations

import json
import math
from typing import Any

import aiosqlite

from ..attention import (
    AttentionEvidenceMode,
    AttentionKind,
    AttentionStatus,
)

def encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def decode_source_ids(value: Any) -> tuple[str, ...] | None:
    """Decode provenance without accepting malformed or ambiguous shapes."""

    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, (list, tuple, set)):
        return None
    if any(
        not isinstance(source_id, str) or not source_id.strip()
        for source_id in parsed
    ):
        return None
    return tuple(
        dict.fromkeys(source_id.strip() for source_id in parsed)
    )


def row_to_session(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "session_id": str(row["session_id"]),
        "user_id": row["user_id"],
        "runtime_agent_id": row["runtime_agent_id"],
        "status": str(row["status"]),
        "started_at": float(row["started_at"]),
        "last_active_at": float(row["last_active_at"]),
        "last_checkpoint_at": (
            float(row["last_checkpoint_at"])
            if row["last_checkpoint_at"]
            else None
        ),
        "metadata": json.loads(row["metadata"] or "{}"),
    }


def row_to_attention_item(row: aiosqlite.Row) -> dict[str, Any]:
    source_turn_ids = decode_source_ids(row["source_turn_ids"])
    source_event_ids = decode_source_ids(row["source_event_ids"])
    if source_turn_ids is None or source_event_ids is None:
        raise ValueError("Malformed L0 attention provenance")
    metadata = json.loads(row["metadata"] or "{}")
    if not isinstance(metadata, dict):
        raise ValueError("Malformed L0 attention metadata")
    kind = str(row["kind"])
    status = str(row["status"])
    evidence_mode = str(row["evidence_mode"])
    try:
        AttentionKind(kind)
        AttentionStatus(status)
        AttentionEvidenceMode(evidence_mode)
    except ValueError as exc:
        raise ValueError("Malformed L0 attention enum") from exc
    summary = str(row["summary"]).strip()
    salience = float(row["salience"])
    confidence = float(row["confidence"])
    first_seen_at = float(row["first_seen_at"])
    last_reinforced_at = float(row["last_reinforced_at"])
    expires_at = (
        float(row["expires_at"])
        if row["expires_at"] is not None
        else None
    )
    numeric_values = [
        salience,
        confidence,
        first_seen_at,
        last_reinforced_at,
        *([expires_at] if expires_at is not None else []),
    ]
    if (
        not summary
        or any(not math.isfinite(value) for value in numeric_values)
        or not 0.0 <= salience <= 1.0
        or not 0.0 <= confidence <= 1.0
    ):
        raise ValueError("Malformed L0 attention values")
    return {
        "item_id": str(row["item_id"]),
        "kind": kind,
        "summary": summary,
        "status": status,
        "salience": salience,
        "confidence": confidence,
        "evidence_mode": evidence_mode,
        "source_turn_ids": list(source_turn_ids),
        "source_event_ids": list(source_event_ids),
        "entity_id": row["entity_id"],
        "task_id": row["task_id"],
        "task_attempt": (
            int(row["task_attempt"])
            if row["task_attempt"] is not None
            else None
        ),
        "first_seen_at": first_seen_at,
        "last_reinforced_at": last_reinforced_at,
        "expires_at": expires_at,
        "supersedes_item_id": row["supersedes_item_id"],
        "metadata": metadata,
    }


__all__ = [
    "decode_source_ids",
    "encode_json",
    "row_to_attention_item",
    "row_to_session",
]
