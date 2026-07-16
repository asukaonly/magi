"""Converge already-stored relationships when graph conflict rules change."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import aiosqlite

from ..graph_conflicts import (
    GraphConflictRule,
    build_exclusive_group_index,
    iter_opposite_predicates,
)
from .versions import append_knowledge_graph_version


class GraphConflictConvergenceError(ValueError):
    """Raised when a new rule cannot safely choose one existing relationship."""


@dataclass(frozen=True, slots=True)
class GraphConflictConvergenceResult:
    """Describe current relationships changed by one rule activation."""

    loser_ids: frozenset[str]
    subject_keys: frozenset[str]


async def converge_existing_graph_conflicts(
    db: aiosqlite.Connection,
    *,
    rule: GraphConflictRule,
    rules: Mapping[str, GraphConflictRule],
    now: float,
) -> GraphConflictConvergenceResult:
    """Close conflicts that predate a newly persisted rule in one transaction."""
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT * FROM knowledge_graph
        WHERE predicate = ? AND status = 'active'
          AND (valid_from IS NULL OR valid_from <= ?)
          AND (valid_to IS NULL OR valid_to > ?)
          AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY subject_id, scope_key, object_id, triple_id
        """,
        (rule.predicate, now, now, now),
    ) as cursor:
        source_rows = await cursor.fetchall()

    loser_ids: set[str] = set()
    subject_keys: set[str] = set()
    processed_opposites: set[tuple[str, str, str, str]] = set()
    processed_exclusive: set[tuple[str, str]] = set()
    group_predicates = (
        build_exclusive_group_index(rules).get(rule.exclusive_group, ())
        if rule.exclusive_group
        else ()
    )
    for source in source_rows:
        current = await _load_retrievable_active_edge(
            db,
            triple_id=str(source["triple_id"]),
            now=now,
        )
        if current is None:
            continue
        for opposite_predicate in iter_opposite_predicates(rule):
            opposite_key = (
                str(current["subject_id"]),
                str(current["object_id"]),
                str(current["scope_key"]),
                opposite_predicate,
            )
            if opposite_key in processed_opposites:
                continue
            processed_opposites.add(opposite_key)
            candidates = await _load_opposite_candidates(
                db,
                source=current,
                opposite_predicate=opposite_predicate,
                now=now,
            )
            result = await _converge_candidate_set(
                db,
                candidates=candidates,
                action=rule.opposite_resolution,
                now=now,
            )
            loser_ids.update(result.loser_ids)
            subject_keys.update(result.subject_keys)

        if rule.exclusive_group:
            exclusive_key = (
                str(current["subject_id"]),
                str(current["scope_key"]),
            )
            if exclusive_key in processed_exclusive:
                continue
            processed_exclusive.add(exclusive_key)
            candidates = await _load_exclusive_candidates(
                db,
                source=current,
                predicates=group_predicates,
                now=now,
            )
            result = await _converge_candidate_set(
                db,
                candidates=candidates,
                action=rule.exclusive_resolution,
                now=now,
            )
            loser_ids.update(result.loser_ids)
            subject_keys.update(result.subject_keys)

    return GraphConflictConvergenceResult(
        loser_ids=frozenset(loser_ids),
        subject_keys=frozenset(subject_keys),
    )


async def _load_retrievable_active_edge(
    db: aiosqlite.Connection,
    *,
    triple_id: str,
    now: float,
) -> aiosqlite.Row | None:
    async with db.execute(
        """
        SELECT * FROM knowledge_graph
        WHERE triple_id = ? AND status = 'active'
          AND (valid_from IS NULL OR valid_from <= ?)
          AND (valid_to IS NULL OR valid_to > ?)
          AND (expires_at IS NULL OR expires_at > ?)
        """,
        (triple_id, now, now, now),
    ) as cursor:
        return await cursor.fetchone()


async def _load_opposite_candidates(
    db: aiosqlite.Connection,
    *,
    source: aiosqlite.Row,
    opposite_predicate: str,
    now: float,
) -> list[aiosqlite.Row]:
    async with db.execute(
        """
        SELECT * FROM knowledge_graph
        WHERE subject_id = ? AND object_id = ? AND scope_key = ?
          AND predicate IN (?, ?) AND status = 'active'
          AND (valid_from IS NULL OR valid_from <= ?)
          AND (valid_to IS NULL OR valid_to > ?)
          AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY triple_id
        """,
        (
            source["subject_id"],
            source["object_id"],
            source["scope_key"],
            source["predicate"],
            opposite_predicate,
            now,
            now,
            now,
        ),
    ) as cursor:
        return list(await cursor.fetchall())


async def _load_exclusive_candidates(
    db: aiosqlite.Connection,
    *,
    source: aiosqlite.Row,
    predicates: Sequence[str],
    now: float,
) -> list[aiosqlite.Row]:
    if not predicates:
        return []
    placeholders = ", ".join("?" for _ in predicates)
    async with db.execute(
        f"""
        SELECT * FROM knowledge_graph
        WHERE subject_id = ? AND scope_key = ?
          AND predicate IN ({placeholders}) AND status = 'active'
          AND (valid_from IS NULL OR valid_from <= ?)
          AND (valid_to IS NULL OR valid_to > ?)
          AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY triple_id
        """,
        (
            source["subject_id"],
            source["scope_key"],
            *predicates,
            now,
            now,
            now,
        ),
    ) as cursor:
        return list(await cursor.fetchall())


async def _converge_candidate_set(
    db: aiosqlite.Connection,
    *,
    candidates: Sequence[aiosqlite.Row],
    action: str,
    now: float,
) -> GraphConflictConvergenceResult:
    unique = {str(row["triple_id"]): row for row in candidates}
    if len(unique) < 2:
        return GraphConflictConvergenceResult(frozenset(), frozenset())

    rows = list(unique.values())
    correction_authority = await _active_correction_authority(db, rows)
    active_corrections = {
        correction_id
        for correction_ids in correction_authority.values()
        for correction_id in correction_ids
    }
    if len(active_corrections) > 1:
        raise GraphConflictConvergenceError(
            "Conflict rule would collapse multiple active user corrections"
        )

    winner = max(
        rows,
        key=lambda row: _winner_rank(
            row,
            has_active_correction=bool(correction_authority.get(str(row["triple_id"]))),
        ),
    )
    winner_id = str(winner["triple_id"])
    losers = [row for row in rows if str(row["triple_id"]) != winner_id]
    next_status = "conflicted" if action == "mark_conflicted" else "deprecated"
    subject_keys: set[str] = set()
    for index, loser in enumerate(losers):
        loser_id = str(loser["triple_id"])
        await append_knowledge_graph_version(
            db,
            triple_id=loser_id,
            created_at=now - 0.000002 + index * 0.0000001,
        )
        await db.execute(
            """
            UPDATE knowledge_graph
            SET status = ?, status_reason = 'graph_conflict_rule',
                deprecated_by = ?, deprecated_at = ?,
                valid_to = CASE
                    WHEN valid_to IS NULL OR valid_to > ? THEN ?
                    ELSE valid_to
                END,
                updated_at = ?
            WHERE triple_id = ? AND status = 'active'
            """,
            (
                next_status,
                winner_id,
                now,
                now,
                now,
                now,
                loser_id,
            ),
        )
        await append_knowledge_graph_version(
            db,
            triple_id=loser_id,
            created_at=now + 0.000001 + index * 0.0000001,
        )
        subject_keys.update(_relationship_subject_keys(loser))
    subject_keys.update(_relationship_subject_keys(winner))
    return GraphConflictConvergenceResult(
        loser_ids=frozenset(str(row["triple_id"]) for row in losers),
        subject_keys=frozenset(subject_keys),
    )


async def _active_correction_authority(
    db: aiosqlite.Connection,
    rows: Sequence[aiosqlite.Row],
) -> dict[str, frozenset[str]]:
    triple_ids = tuple(str(row["triple_id"]) for row in rows)
    placeholders = ", ".join("?" for _ in triple_ids)
    authority: dict[str, set[str]] = {triple_id: set() for triple_id in triple_ids}
    async with db.execute(
        f"""
        SELECT correction_id, replacement_target_id
        FROM memory_corrections
        WHERE target_kind = 'edge' AND state = 'active'
          AND replacement_target_id IN ({placeholders})
        """,
        triple_ids,
    ) as cursor:
        for correction in await cursor.fetchall():
            replacement_id = str(correction["replacement_target_id"] or "")
            if replacement_id in authority:
                authority[replacement_id].add(str(correction["correction_id"]))

    correction_ids = {
        value.removeprefix("correction:")
        for row in rows
        if (value := str(row["authority_ref"] or "")).startswith("correction:")
    }
    if correction_ids:
        correction_placeholders = ", ".join("?" for _ in correction_ids)
        async with db.execute(
            f"""
            SELECT correction_id FROM memory_corrections
            WHERE correction_id IN ({correction_placeholders}) AND state = 'active'
            """,
            tuple(sorted(correction_ids)),
        ) as cursor:
            active_ids = {str(row["correction_id"]) for row in await cursor.fetchall()}
        for row in rows:
            raw_ref = str(row["authority_ref"] or "")
            if raw_ref.startswith("correction:"):
                correction_id = raw_ref.removeprefix("correction:")
                if correction_id in active_ids:
                    authority[str(row["triple_id"])].add(correction_id)
    return {triple_id: frozenset(correction_ids) for triple_id, correction_ids in authority.items()}


def _winner_rank(
    row: aiosqlite.Row,
    *,
    has_active_correction: bool,
) -> tuple[Any, ...]:
    return (
        has_active_correction,
        str(row["evidence_class"] or "") == "user_self_report"
        or str(row["source_type"] or "") == "user_correction",
        float(row["last_confirmed_at"] or 0.0),
        float(row["last_observed_at"] or 0.0),
        float(row["updated_at"] or 0.0),
        float(row["created_at"] or 0.0),
        float(row["confidence"] or 0.0),
        str(row["triple_id"]),
    )


def _relationship_subject_keys(row: aiosqlite.Row) -> set[str]:
    keys = {str(row["subject_id"])}
    object_id = str(row["object_id"] or "")
    if ":" in object_id:
        keys.add(object_id)
    return {item for item in keys if item}


__all__ = [
    "GraphConflictConvergenceError",
    "GraphConflictConvergenceResult",
    "converge_existing_graph_conflicts",
]
