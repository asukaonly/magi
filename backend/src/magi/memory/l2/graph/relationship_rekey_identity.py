"""Conflict-aware identity and payload helpers for relationship rekeys."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, overload

import aiosqlite

from ..corrections.fingerprints import (
    relationship_claim_fingerprint,
    relationship_slot_key,
)
from ..graph_conflicts import (
    GraphConflictRule,
    build_graph_conflict_matrix,
    relationship_predicate_slot,
)


async def relationship_slot_key_on_connection(
    db: aiosqlite.Connection,
    *,
    subject_id: str,
    predicate: str,
    object_id: str,
) -> str:
    """Build the same conflict-aware slot identity used by graph writes."""
    normalized_predicate = str(predicate).strip().upper()
    async with db.execute(
        """
        SELECT predicate, opposite_predicates, opposite_resolution,
               exclusive_group, exclusive_scope, exclusive_resolution
        FROM graph_conflict_rules
        WHERE predicate = ?
        """,
        (normalized_predicate,),
    ) as cursor:
        rule = await cursor.fetchone()
    rules = build_graph_conflict_matrix()
    if rule is not None:
        normalized_rule = GraphConflictRule.from_mapping(dict(rule))
        rules[normalized_rule.predicate] = normalized_rule
    return str(
        relationship_slot_key(
            subject_id=subject_id,
            predicate=normalized_predicate,
            object_id=object_id,
            predicate_slot=relationship_predicate_slot(
                rules,
                predicate=normalized_predicate,
                object_id=object_id,
            ),
        )
    )


async def _set_payload_identity(
    db: aiosqlite.Connection,
    payload: dict[str, Any],
    *,
    triple_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
) -> None:
    scope_key = str(payload.get("scope_key") or "global")
    slot_key = await relationship_slot_key_on_connection(
        db,
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
    )
    payload.update(
        {
            "triple_id": triple_id,
            "subject_id": subject_id,
            "predicate": predicate,
            "object_id": object_id,
            "slot_key": slot_key,
            "claim_fingerprint": relationship_claim_fingerprint(
                slot_key_value=slot_key,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                scope_key_value=scope_key,
            ),
        }
    )


@overload
def _decode_payload(
    raw: Any,
    correction_id: Any,
    *,
    allow_none: Literal[False] = False,
) -> dict[str, Any]: ...


@overload
def _decode_payload(
    raw: Any,
    correction_id: Any,
    *,
    allow_none: Literal[True],
) -> dict[str, Any] | None: ...


def _decode_payload(
    raw: Any,
    correction_id: Any,
    *,
    allow_none: bool = False,
) -> dict[str, Any] | None:
    if raw is None and allow_none:
        return None
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Correction payload is invalid: {correction_id}") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"Correction payload is not an object: {correction_id}")
    return decoded


def _encode_payload(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
