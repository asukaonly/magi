"""Block ambiguous correction reverts created by identity merges.

Revision ID: v29_correction_revert_blocks
Revises: v28_time_range_forget_barriers
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from alembic import op

revision = "v29_correction_revert_blocks"
down_revision = "v28_time_range_forget_barriers"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE memory_correction_revert_blocks (
    correction_id TEXT PRIMARY KEY,
    block_reason TEXT NOT NULL CHECK(
        block_reason IN ('identity_merge', 'lineage_collision')
    ),
    created_at REAL NOT NULL,
    FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id)
        ON DELETE CASCADE
);
CREATE INDEX idx_memory_correction_revert_blocks_reason
    ON memory_correction_revert_blocks(block_reason, created_at, correction_id);
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_memory_correction_revert_blocks_reason;
DROP TABLE IF EXISTS memory_correction_revert_blocks;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a new shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v29_correction_revert_blocks")
    try:
        connection.execute(
            """
            CREATE TABLE memory_correction_revert_blocks (
                correction_id TEXT PRIMARY KEY,
                block_reason TEXT NOT NULL CHECK(
                    block_reason IN ('identity_merge', 'lineage_collision')
                ),
                created_at REAL NOT NULL,
                FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id)
                    ON DELETE CASCADE
            )
            """
        )
        _backfill_colliding_lineages(connection)
        connection.execute(
            """
            CREATE INDEX idx_memory_correction_revert_blocks_reason
            ON memory_correction_revert_blocks(
                block_reason, created_at, correction_id
            )
            """
        )
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v29_correction_revert_blocks")
        connection.execute("RELEASE SAVEPOINT v29_correction_revert_blocks")
        raise
    connection.execute("RELEASE SAVEPOINT v29_correction_revert_blocks")


def _backfill_colliding_lineages(connection) -> None:
    cursor = connection.execute(
        """
        SELECT correction_id, target_kind, target_id, replacement_target_id,
               slot_key, scope_json, before_json, replacement_json, created_at
        FROM memory_corrections
        WHERE state = 'active'
          AND transition_cancelled_at IS NULL
        ORDER BY target_kind, slot_key, created_at, correction_id
        """
    )
    columns = [str(item[0]) for item in cursor.description]
    rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for slot_key, scope_key in _stored_governance_keys(row):
            groups[(str(row["target_kind"]), slot_key, scope_key)].append(row)
    blocked: set[str] = set()
    for candidates in groups.values():
        if len(candidates) < 2:
            continue
        components = _lineage_components(candidates)
        if len(components) > 1:
            blocked.update(
                str(candidate["correction_id"])
                for component in components
                for candidate in component
            )
    connection.executemany(
        """
        INSERT INTO memory_correction_revert_blocks(
            correction_id, block_reason, created_at
        ) VALUES (?, 'lineage_collision', ?)
        """,
        [
            (
                correction_id,
                float(
                    next(
                        row["created_at"]
                        for row in rows
                        if str(row["correction_id"]) == correction_id
                    )
                ),
            )
            for correction_id in sorted(blocked)
        ],
    )


def _lineage_components(
    corrections: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
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


def _stored_governance_keys(
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
    return json.dumps(
        dict(raw_scope),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


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


def downgrade() -> None:
    connection = op.get_bind().connection
    retained = connection.execute("SELECT COUNT(*) FROM memory_correction_revert_blocks").fetchone()
    if retained is not None and int(retained[0]) > 0:
        raise RuntimeError("Cannot downgrade correction revert blocks while history exists")
    connection.execute("SAVEPOINT v29_correction_revert_blocks_down")
    try:
        connection.execute("DROP INDEX IF EXISTS idx_memory_correction_revert_blocks_reason")
        connection.execute("DROP TABLE IF EXISTS memory_correction_revert_blocks")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v29_correction_revert_blocks_down")
        connection.execute("RELEASE SAVEPOINT v29_correction_revert_blocks_down")
        raise
    connection.execute("RELEASE SAVEPOINT v29_correction_revert_blocks_down")


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
