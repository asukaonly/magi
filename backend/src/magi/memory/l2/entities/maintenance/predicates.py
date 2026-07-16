"""Open predicate consolidation helpers for L2 entity maintenance."""

from __future__ import annotations

import time
from typing import Protocol, cast

import aiosqlite

from .....core.logger import get_logger
from .....core.sqlite import sqlite_connection_async
from ...graph.identity_rekey import (
    RelationshipIdentityRekeyResult,
    rekey_relationship_identity,
    rewrite_materialized_relationship_references,
)
from ...ontology import PREDICATE_REGISTRY

logger = get_logger("magi.memory.l2.entities.maintenance")


class _PredicateMaintenanceStatsProtocol(Protocol):
    open_predicates_consolidated: int


class _PredicateMaintenanceHostProtocol(Protocol):
    _db_path: str


class L2EntityPredicateMaintenanceMixin:
    """Consolidate open predicates into core ontology predicates where possible."""

    async def _consolidate_open_predicates(
        self,
        stats: _PredicateMaintenanceStatsProtocol,
    ) -> None:
        """Rewrite non-core predicates to their core synonym when a mapping exists."""
        host = self._predicate_maintenance_host()
        core_preds_by_group = _core_predicates_by_synonym_group()

        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
            consolidated = 0
            invalidated_vector_ids: set[str] = set()
            rewritten_references: dict[str, str] = {}
            now = time.time()
            await db.execute("BEGIN IMMEDIATE")
            try:
                rows = await _fetch_active_knowledge_graph_rows(db)
                for row in rows:
                    core_predicates = _matching_core_predicates(row, core_preds_by_group)
                    if not core_predicates:
                        continue
                    result = await _consolidate_open_predicate_row(db, row, core_predicates, now)
                    if result.triple_id is None:
                        continue
                    invalidated_vector_ids.update(result.invalidated_vector_ids)
                    rewritten_references.update(result.rewritten_reference_ids)
                    consolidated += 1
                await rewrite_materialized_relationship_references(
                    db,
                    rewritten_references,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
            stats.open_predicates_consolidated = consolidated
        vector_index = getattr(host, "_edge_vector_index", None)
        if vector_index is not None:
            for triple_id in sorted(invalidated_vector_ids):
                try:
                    await vector_index.delete_entity(entity_id=triple_id)
                except Exception as exc:
                    logger.warning(
                        "L2 relationship vector cleanup failed",
                        triple_id=triple_id,
                        error=str(exc),
                    )

    def _predicate_maintenance_host(self) -> _PredicateMaintenanceHostProtocol:
        return self  # type: ignore[return-value]


async def _fetch_active_knowledge_graph_rows(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    return cast(
        list[aiosqlite.Row],
        await db.execute_fetchall("""
            SELECT triple_id, subject_id, predicate, object_id,
                   scope_key
            FROM knowledge_graph
            WHERE status = 'active'
            """),
    )


def _core_predicates_by_synonym_group() -> dict[str, list[str]]:
    core_preds_by_group: dict[str, list[str]] = {}
    for predicate in sorted(PREDICATE_REGISTRY):
        group = _predicate_synonym_group(predicate)
        if group:
            core_preds_by_group.setdefault(group, []).append(predicate)
    return core_preds_by_group


def _matching_core_predicates(
    row: aiosqlite.Row,
    core_preds_by_group: dict[str, list[str]],
) -> list[str] | None:
    predicate = str(row["predicate"]).strip().upper()
    if predicate in PREDICATE_REGISTRY:
        return None
    group = _predicate_synonym_group(predicate)
    if group is None:
        return None
    return core_preds_by_group.get(group)


async def _consolidate_open_predicate_row(
    db: aiosqlite.Connection,
    row: aiosqlite.Row,
    core_predicates: list[str],
    now: float,
) -> RelationshipIdentityRekeyResult:
    existing = await _fetch_existing_core_predicates(db, row, core_predicates)
    target_predicate = str(existing[0]["predicate"]) if existing else core_predicates[0]
    return await rekey_relationship_identity(
        db,
        source_triple_id=str(row["triple_id"]),
        subject_id=str(row["subject_id"]),
        predicate=target_predicate,
        object_id=str(row["object_id"]),
        now=now,
        rewrite_materialized_references=False,
    )


async def _fetch_existing_core_predicates(
    db: aiosqlite.Connection,
    row: aiosqlite.Row,
    core_predicates: list[str],
) -> list[aiosqlite.Row]:
    placeholders = ",".join("?" * len(core_predicates))
    return cast(
        list[aiosqlite.Row],
        await db.execute_fetchall(
            f"""
            SELECT triple_id, predicate, evidence_event_ids,
                   observation_count, confidence,
                   first_observed_at, last_observed_at
            FROM knowledge_graph
            WHERE subject_id = ? AND object_id = ?
              AND predicate IN ({placeholders})
              AND scope_key = ?
              AND triple_id != ? AND status = 'active'
            ORDER BY predicate, triple_id
            """,
            (
                row["subject_id"],
                row["object_id"],
                *core_predicates,
                row["scope_key"],
                row["triple_id"],
            ),
        ),
    )


def _predicate_synonym_group(predicate: str) -> str | None:
    from . import get_predicate_synonym_group

    return cast(str | None, get_predicate_synonym_group(predicate))
