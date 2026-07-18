"""Durable safety blocks for correction reverts that became ambiguous."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

import aiosqlite

from .fingerprints import canonical_scope_json
from .models import CorrectionTargetKind

IDENTITY_MERGE_REVERT_BLOCK = "identity_merge"
LINEAGE_COLLISION_REVERT_BLOCK = "lineage_collision"
_REVERT_BLOCK_REASONS = frozenset(
    {
        IDENTITY_MERGE_REVERT_BLOCK,
        LINEAGE_COLLISION_REVERT_BLOCK,
    }
)
_REPLACEMENT_SLOT_SQL = (
    "CASE WHEN json_valid(replacement_json) THEN json_extract(replacement_json, '$.slot_key') END"
)
_SLOT_QUERY_CHUNK_SIZE = 200


async def block_colliding_correction_lineages(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    slot_keys: Iterable[str],
    block_reason: str,
    created_at: float,
) -> set[str]:
    """Block independent active correction chains that converge on one slot."""
    _validate_revert_block_reason(block_reason)
    normalized_slots = sorted(
        {str(slot_key).strip() for slot_key in slot_keys if str(slot_key).strip()}
    )
    if not normalized_slots:
        return set()
    rows_by_id: dict[str, dict[str, Any]] = {}
    for start in range(0, len(normalized_slots), _SLOT_QUERY_CHUNK_SIZE):
        slot_chunk = normalized_slots[start : start + _SLOT_QUERY_CHUNK_SIZE]
        placeholders = ", ".join("?" for _ in slot_chunk)
        async with db.execute(
            f"""
            SELECT *
            FROM (
                SELECT correction_id, target_id, replacement_target_id,
                       slot_key, scope_json, before_json, replacement_json,
                       created_at
                FROM memory_corrections
                WHERE target_kind = ?
                  AND state = 'active'
                  AND transition_cancelled_at IS NULL
                  AND slot_key IN ({placeholders})
                UNION
                SELECT correction_id, target_id, replacement_target_id,
                       slot_key, scope_json, before_json, replacement_json,
                       created_at
                FROM memory_corrections
                WHERE target_kind = ?
                  AND state = 'active'
                  AND transition_cancelled_at IS NULL
                  AND {_REPLACEMENT_SLOT_SQL} IN ({placeholders})
            )
            ORDER BY created_at, correction_id
            """,
            (
                target_kind.value,
                *slot_chunk,
                target_kind.value,
                *slot_chunk,
            ),
        ) as cursor:
            for row in await cursor.fetchall():
                normalized = dict(row)
                rows_by_id[str(normalized["correction_id"])] = normalized
    rows = sorted(
        rows_by_id.values(),
        key=lambda row: (
            float(row.get("created_at") or 0.0),
            str(row["correction_id"]),
        ),
    )
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for governance_key in _stored_correction_governance_keys(row):
            if governance_key[0] in normalized_slots:
                groups[governance_key].append(row)
    correction_ids: set[str] = set()
    for candidates in groups.values():
        if len(candidates) < 2:
            continue
        components = _lineage_components(candidates)
        if len(components) > 1:
            correction_ids.update(
                str(candidate["correction_id"])
                for component in components
                for candidate in component
            )
    if not correction_ids:
        return set()
    return await block_correction_reverts(
        db,
        correction_ids=correction_ids,
        block_reason=block_reason,
        created_at=created_at,
    )


async def block_correction_reverts(
    db: aiosqlite.Connection,
    *,
    correction_ids: Iterable[str],
    block_reason: str,
    created_at: float,
) -> set[str]:
    """Durably prevent explicitly unsafe correction reverts."""
    _validate_revert_block_reason(block_reason)
    normalized_ids = sorted(
        {
            str(correction_id).strip()
            for correction_id in correction_ids
            if str(correction_id).strip()
        }
    )
    if not normalized_ids:
        return set()
    await db.executemany(
        """
        INSERT INTO memory_correction_revert_blocks(
            correction_id, block_reason, created_at
        ) VALUES (?, ?, ?)
        ON CONFLICT(correction_id) DO NOTHING
        """,
        [
            (
                correction_id,
                block_reason,
                created_at,
            )
            for correction_id in normalized_ids
        ],
    )
    return set(normalized_ids)


def _validate_revert_block_reason(block_reason: str) -> None:
    if block_reason not in _REVERT_BLOCK_REASONS:
        raise ValueError(f"Unsupported correction revert block reason: {block_reason}")


def _lineage_components(
    corrections: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Return connected correction chains using only explicit forward handoffs."""
    by_id = {str(correction["correction_id"]): correction for correction in corrections}
    adjacency = {correction_id: set() for correction_id in by_id}
    ordered = sorted(
        corrections,
        key=lambda item: (
            float(item.get("created_at") or 0.0),
            str(item["correction_id"]),
        ),
    )
    predecessors: dict[str, list[dict[str, Any]]] = defaultdict(list)
    successors: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for correction in ordered:
        successors[str(correction.get("target_id") or "").strip()].append(correction)
        replacement_id = str(correction.get("replacement_target_id") or "").strip()
        target_id = str(correction.get("target_id") or "").strip()
        if replacement_id and replacement_id != target_id:
            predecessors[replacement_id].append(correction)
    for handoff_id in predecessors.keys() & successors.keys():
        earlier_candidates = predecessors[handoff_id]
        later_candidates = successors[handoff_id]
        if len(earlier_candidates) != 1 or len(later_candidates) != 1:
            continue
        earlier = earlier_candidates[0]
        later = later_candidates[0]
        replacement_id = str(earlier.get("replacement_target_id") or "").strip()
        if replacement_id != str(later.get("target_id") or "").strip():
            continue
        earlier_id = str(earlier["correction_id"])
        earlier_created_at = float(earlier.get("created_at") or 0.0)
        later_id = str(later["correction_id"])
        if later_id == earlier_id or float(later.get("created_at") or 0.0) < earlier_created_at:
            continue
        adjacency[earlier_id].add(later_id)
        adjacency[later_id].add(earlier_id)
    components: list[list[dict[str, Any]]] = []
    remaining = set(by_id)
    while remaining:
        root = min(remaining)
        stack = [root]
        component_ids: set[str] = set()
        while stack:
            correction_id = stack.pop()
            if correction_id in component_ids:
                continue
            component_ids.add(correction_id)
            stack.extend(adjacency[correction_id] - component_ids)
        remaining -= component_ids
        components.append([by_id[correction_id] for correction_id in sorted(component_ids)])
    return components


def _stored_correction_governance_keys(
    correction: Mapping[str, Any],
) -> set[tuple[str, str]]:
    before = _decode_object(correction.get("before_json"))
    before_slot = str(before.get("slot_key") or correction.get("slot_key") or "").strip()
    keys = {(before_slot, _stored_payload_scope_key(before))} if before_slot else set()
    replacement = _decode_optional_object(correction.get("replacement_json"))
    if replacement is None:
        return keys
    replacement_slot = str(replacement.get("slot_key") or before_slot).strip()
    if replacement_slot:
        keys.add(
            (
                replacement_slot,
                _stored_payload_scope_key(
                    replacement,
                    fallback=correction.get("scope_json"),
                ),
            )
        )
    return keys


def _stored_payload_scope_key(
    payload: Mapping[str, Any],
    *,
    fallback: Any = None,
) -> str:
    raw_scope = payload.get("scope_json", payload.get("scope"))
    if raw_scope in (None, ""):
        raw_scope = fallback
    if isinstance(raw_scope, str):
        raw_scope = json.loads(raw_scope)
    if raw_scope in (None, ""):
        raw_scope = {}
    if not isinstance(raw_scope, Mapping):
        raise ValueError("Stored correction scope is not an object")
    return canonical_scope_json(raw_scope)


def _decode_object(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError("Stored correction payload is not an object")
    return parsed


def _decode_optional_object(value: Any) -> dict[str, Any] | None:
    if value in (None, ""):
        return None
    return _decode_object(value)


async def correction_revert_block_reason_on_connection(
    db: aiosqlite.Connection,
    correction_id: str,
) -> str | None:
    """Return the durable reason one correction can no longer be reverted."""
    async with db.execute(
        """
        SELECT block_reason
        FROM memory_correction_revert_blocks
        WHERE correction_id = ?
        """,
        (correction_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    reason = str(row[0] or "").strip()
    return reason or None


__all__ = [
    "IDENTITY_MERGE_REVERT_BLOCK",
    "LINEAGE_COLLISION_REVERT_BLOCK",
    "block_correction_reverts",
    "block_colliding_correction_lineages",
    "correction_revert_block_reason_on_connection",
]
