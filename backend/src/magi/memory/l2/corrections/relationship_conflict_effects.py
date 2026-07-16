"""Reversible graph conflicts caused by authoritative relationship corrections."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import aiosqlite

from ..graph.versions import append_knowledge_graph_version
from ..graph_conflicts import (
    DEFAULT_GRAPH_CONFLICT_RULES,
    GraphConflictRule,
    build_exclusive_group_index,
    iter_opposite_predicates,
)

_STATUS_REASON_PREFIX = "user_correction_conflict:"


@dataclass(frozen=True)
class RelationshipConflictEffects:
    """Relationships suppressed or restored by one correction transaction."""

    edge_ids: tuple[str, ...] = ()
    subject_keys: tuple[str, ...] = ()


async def apply_relationship_conflict_effects(
    db: aiosqlite.Connection,
    *,
    replacement: Mapping[str, Any],
    correction_id: str,
    graph_conflict_rules: Mapping[str, GraphConflictRule],
    effective_at: float,
    now: float,
) -> RelationshipConflictEffects:
    """Suppress active conflicts while retaining enough history for revert."""
    predicate = str(replacement["predicate"])
    rule = graph_conflict_rules.get(predicate)
    if rule is None:
        return RelationshipConflictEffects()

    affected: list[tuple[str, str, str]] = []
    for opposite_predicate in iter_opposite_predicates(rule):
        rows = await _active_conflicts(
            db,
            query="""
                SELECT *
                FROM knowledge_graph
                WHERE subject_id = ? AND object_id = ? AND predicate = ?
                  AND scope_key = ? AND triple_id != ? AND status = 'active'
            """,
            args=(
                str(replacement["subject_id"]),
                str(replacement["object_id"]),
                opposite_predicate,
                str(replacement["scope_key"]),
                str(replacement["triple_id"]),
            ),
            effective_at=effective_at,
        )
        affected.extend(
            await _suppress_conflicts(
                db,
                rows=rows,
                replacement_id=str(replacement["triple_id"]),
                correction_id=correction_id,
                next_status=_status_from_action(rule.opposite_resolution),
                effective_at=effective_at,
                now=now,
                version_offset=len(affected),
            )
        )

    if rule.exclusive_group:
        group_predicates = build_exclusive_group_index(graph_conflict_rules).get(
            rule.exclusive_group,
            (),
        )
        if group_predicates:
            placeholders = ", ".join("?" for _ in group_predicates)
            rows = await _active_conflicts(
                db,
                query=f"""
                    SELECT *
                    FROM knowledge_graph
                    WHERE subject_id = ? AND predicate IN ({placeholders})
                      AND scope_key = ? AND triple_id != ? AND status = 'active'
                      AND (predicate != ? OR object_id != ?)
                """,
                args=(
                    str(replacement["subject_id"]),
                    *group_predicates,
                    str(replacement["scope_key"]),
                    str(replacement["triple_id"]),
                    predicate,
                    str(replacement["object_id"]),
                ),
                effective_at=effective_at,
            )
            affected.extend(
                await _suppress_conflicts(
                    db,
                    rows=rows,
                    replacement_id=str(replacement["triple_id"]),
                    correction_id=correction_id,
                    next_status=_status_from_action(rule.exclusive_resolution),
                    effective_at=effective_at,
                    now=now,
                    version_offset=len(affected),
                )
            )

    return _effects(affected)


async def restore_relationship_conflict_effects(
    db: aiosqlite.Connection,
    *,
    correction_id: str,
    replacement_id: str | None,
    now: float,
) -> RelationshipConflictEffects:
    """Restore only conflicts still owned by the correction being reverted."""
    if not replacement_id:
        return RelationshipConflictEffects()
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT effects.*, graph.subject_id, graph.object_id,
               graph.status AS current_status,
               graph.deprecated_by AS current_deprecated_by
        FROM memory_relationship_conflict_effects AS effects
        LEFT JOIN knowledge_graph AS graph
          ON graph.triple_id = effects.victim_triple_id
        WHERE effects.correction_id = ? AND effects.restored_at IS NULL
          AND effects.replacement_triple_id = ?
        ORDER BY effects.created_at, effects.effect_id
        """,
        (correction_id, replacement_id),
    ) as cursor:
        rows = await cursor.fetchall()

    affected: list[tuple[str, str, str]] = []
    for index, row in enumerate(rows):
        triple_id = str(row["victim_triple_id"])
        if row["subject_id"] is not None:
            affected.append((triple_id, str(row["subject_id"]), str(row["object_id"])))
        still_owned = (
            row["current_status"] in {"deprecated", "conflicted"}
            and str(row["current_deprecated_by"] or "") == replacement_id
        )
        if still_owned:
            version_at = now + (index * 0.000004)
            await append_knowledge_graph_version(
                db,
                triple_id=triple_id,
                correction_id=correction_id,
                created_at=version_at,
            )
            update = await db.execute(
                """
                UPDATE knowledge_graph
                SET status = ?, status_reason = ?, deprecated_by = ?,
                    deprecated_at = ?, valid_to = ?, updated_at = ?
                WHERE triple_id = ? AND deprecated_by = ?
                  AND status IN ('deprecated', 'conflicted')
                """,
                (
                    row["pre_status"],
                    row["pre_status_reason"],
                    row["pre_deprecated_by"],
                    row["pre_deprecated_at"],
                    row["pre_valid_to"],
                    now,
                    triple_id,
                    replacement_id,
                ),
            )
            if int(update.rowcount or 0) > 0:
                await append_knowledge_graph_version(
                    db,
                    triple_id=triple_id,
                    correction_id=correction_id,
                    created_at=version_at + 0.000001,
                )
        await db.execute(
            """
            UPDATE memory_relationship_conflict_effects
            SET restored_at = ?
            WHERE effect_id = ? AND restored_at IS NULL
            """,
            (now, row["effect_id"]),
        )
    return _effects(affected)


async def relationship_conflict_effects_on_connection(
    db: aiosqlite.Connection,
    *,
    correction_id: str,
    replacement_id: str | None,
) -> RelationshipConflictEffects:
    """Load conflict effects that are still owned by an active correction."""
    if not replacement_id:
        return RelationshipConflictEffects()
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT effects.victim_triple_id, graph.subject_id, graph.object_id
        FROM memory_relationship_conflict_effects AS effects
        JOIN knowledge_graph AS graph
          ON graph.triple_id = effects.victim_triple_id
        WHERE effects.correction_id = ? AND effects.restored_at IS NULL
          AND effects.replacement_triple_id = ?
        ORDER BY effects.created_at, effects.effect_id
        """,
        (correction_id, replacement_id),
    ) as cursor:
        rows = await cursor.fetchall()
    return _effects(
        [
            (
                str(row["victim_triple_id"]),
                str(row["subject_id"]),
                str(row["object_id"]),
            )
            for row in rows
        ]
    )


async def record_relationship_shadow_conflict_effect(
    db: aiosqlite.Connection,
    *,
    correction_id: str,
    victim: Mapping[str, Any],
    replacement_id: str,
    now: float,
) -> None:
    """Record the reversible owner before an authority turns a fact into a shadow."""
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT effective_at, created_at
        FROM memory_corrections
        WHERE correction_id = ? AND state = 'active'
          AND replacement_target_id = ?
        """,
        (correction_id, replacement_id),
    ) as cursor:
        correction = await cursor.fetchone()
    if correction is None:
        return
    effective_at = float(correction["effective_at"] or correction["created_at"])
    await _record_conflict_effect(
        db,
        row=victim,
        correction_id=correction_id,
        replacement_id=replacement_id,
        effective_at=effective_at,
        created_at=now,
    )


async def load_relationship_graph_conflict_rules(
    db: aiosqlite.Connection,
) -> dict[str, GraphConflictRule]:
    """Load the persisted conflict matrix with built-in defaults."""
    db.row_factory = aiosqlite.Row
    rules = dict(DEFAULT_GRAPH_CONFLICT_RULES)
    async with db.execute(
        """
        SELECT predicate, opposite_predicates, opposite_resolution,
               exclusive_group, exclusive_scope, exclusive_resolution
        FROM graph_conflict_rules
        ORDER BY predicate ASC
        """
    ) as cursor:
        rows = await cursor.fetchall()
    for row in rows:
        rule = GraphConflictRule.from_mapping(dict(row))
        rules[rule.predicate] = rule
    return rules


async def _active_conflicts(
    db: aiosqlite.Connection,
    *,
    query: str,
    args: tuple[Any, ...],
    effective_at: float,
) -> list[aiosqlite.Row]:
    db.row_factory = aiosqlite.Row
    async with db.execute(query, args) as cursor:
        rows = await cursor.fetchall()
    return [row for row in rows if row["valid_to"] is None or float(row["valid_to"]) > effective_at]


async def _suppress_conflicts(
    db: aiosqlite.Connection,
    *,
    rows: list[aiosqlite.Row],
    replacement_id: str,
    correction_id: str,
    next_status: str,
    effective_at: float,
    now: float,
    version_offset: int,
) -> list[tuple[str, str, str]]:
    affected: list[tuple[str, str, str]] = []
    reason = _status_reason(correction_id)
    for index, row in enumerate(rows):
        triple_id = str(row["triple_id"])
        valid_from = float(row["valid_from"]) if row["valid_from"] is not None else effective_at
        closure_at = max(effective_at, valid_from)
        if row["valid_to"] is not None:
            closure_at = min(closure_at, float(row["valid_to"]))
        version_index = version_offset + index
        await _record_conflict_effect(
            db,
            row=row,
            correction_id=correction_id,
            replacement_id=replacement_id,
            effective_at=effective_at,
            created_at=now,
        )
        await append_knowledge_graph_version(
            db,
            triple_id=triple_id,
            correction_id=correction_id,
            created_at=now + (version_index * 0.000004),
        )
        update = await db.execute(
            """
            UPDATE knowledge_graph
            SET status = ?, status_reason = ?, deprecated_by = ?,
                deprecated_at = ?, valid_to = ?, updated_at = ?
            WHERE triple_id = ? AND status = 'active'
            """,
            (
                next_status,
                reason,
                replacement_id,
                effective_at,
                closure_at,
                now,
                triple_id,
            ),
        )
        if int(update.rowcount or 0) <= 0:
            continue
        await append_knowledge_graph_version(
            db,
            triple_id=triple_id,
            correction_id=correction_id,
            created_at=now + (version_index * 0.000004) + 0.000001,
        )
        affected.append((triple_id, str(row["subject_id"]), str(row["object_id"])))
    return affected


async def _record_conflict_effect(
    db: aiosqlite.Connection,
    *,
    row: Mapping[str, Any],
    correction_id: str,
    replacement_id: str,
    effective_at: float,
    created_at: float,
) -> None:
    snapshot = dict(row)
    await db.execute(
        """
        INSERT INTO memory_relationship_conflict_effects(
            effect_id, correction_id, victim_triple_id, replacement_triple_id,
            pre_status, pre_status_reason, pre_deprecated_by, pre_deprecated_at,
            pre_valid_to, effective_at, created_at, restored_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(correction_id, victim_triple_id) DO NOTHING
        """,
        (
            f"relationship_conflict_effect_{uuid.uuid4().hex}",
            correction_id,
            str(snapshot["triple_id"]),
            replacement_id,
            str(snapshot.get("status") or "active"),
            snapshot.get("status_reason"),
            snapshot.get("deprecated_by"),
            snapshot.get("deprecated_at"),
            snapshot.get("valid_to"),
            effective_at,
            created_at,
        ),
    )


def _status_reason(correction_id: str) -> str:
    return f"{_STATUS_REASON_PREFIX}{correction_id}"


def _status_from_action(action: str) -> str:
    return "conflicted" if action == "mark_conflicted" else "deprecated"


def _effects(rows: list[tuple[str, str, str]]) -> RelationshipConflictEffects:
    subject_keys: list[str] = []
    for _, subject_id, object_id in rows:
        if subject_id:
            subject_keys.append(subject_id)
        if ":" in object_id:
            subject_keys.append(object_id)
    return RelationshipConflictEffects(
        edge_ids=tuple(dict.fromkeys(triple_id for triple_id, _, _ in rows)),
        subject_keys=tuple(dict.fromkeys(subject_keys)),
    )


__all__ = [
    "RelationshipConflictEffects",
    "apply_relationship_conflict_effects",
    "load_relationship_graph_conflict_rules",
    "record_relationship_shadow_conflict_effect",
    "relationship_conflict_effects_on_connection",
    "restore_relationship_conflict_effects",
]
