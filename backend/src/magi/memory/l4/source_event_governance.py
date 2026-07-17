"""Source-event governance for L4 procedural memory."""

from __future__ import annotations

from collections.abc import Iterable
import time
from typing import Any

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..source_event_governance import (
    normalize_source_event_ids,
    source_event_derivation_block_ids,
    source_event_derivation_block_predicate,
    source_event_tombstone_ids,
    tombstone_source_event_ids,
)
from .table_names import (
    EXECUTION_TRACES_TABLE,
    SKILL_CHUNKS_TABLE,
    SKILL_EVENT_LINKS_TABLE,
)

_FORGET_BATCH_SIZE = 100
_EVENT_BATCH_SIZE = 500
_VECTOR_ENTITY_BATCH_SIZE = 500
_FORGOTTEN_CATEGORY = "__forgotten__"


def active_skill_predicate(alias: str = "skills") -> str:
    """Return the fail-closed SQL predicate for one procedural skill alias."""
    return f"""
        {alias}.deleted_at IS NULL
        AND NOT EXISTS (
            SELECT 1
            FROM {SKILL_EVENT_LINKS_TABLE} AS governed_links
            JOIN memory_source_event_tombstones AS governed_events
              ON governed_events.event_id = governed_links.event_id
            WHERE governed_links.skill_id = {alias}.skill_id
        )
        AND NOT EXISTS (
            SELECT 1
            FROM {SKILL_EVENT_LINKS_TABLE} AS projection_links
            JOIN memory_projection_blocks AS projection_blocks
              ON projection_blocks.event_id = projection_links.event_id
             AND {source_event_derivation_block_predicate("projection_blocks")}
            WHERE projection_links.skill_id = {alias}.skill_id
        )
    """


async def link_skill_source_event(
    db: aiosqlite.Connection,
    *,
    skill_id: str,
    event_id: str,
    created_at: float,
) -> None:
    """Persist complete L4 evidence lineage without truncating older links."""
    normalized = normalize_source_event_ids([event_id])
    if not normalized:
        return
    await db.execute(
        f"""
        INSERT OR IGNORE INTO {SKILL_EVENT_LINKS_TABLE}(skill_id, event_id, created_at)
        VALUES (?, ?, ?)
        """,
        (skill_id, normalized[0], float(created_at)),
    )


async def skill_accepts_source_event(
    db: aiosqlite.Connection,
    *,
    event_id: str,
    turn_id: str | None = None,
) -> bool:
    """Return whether an incoming event or its owning turn may update L4 state."""
    source_references = normalize_source_event_ids([event_id, turn_id or ""])
    if await source_event_tombstone_ids(db, source_references):
        return False
    return not bool(
        await source_event_derivation_block_ids(
            db,
            source_references,
        )
    )


class L4SourceEventGovernanceMixin:
    """Forget L4 skills whose learned state depends on deleted source events."""

    db_path: str
    _vector_index: Any | None

    async def initialize(self) -> None:
        raise NotImplementedError

    def embedding_mutation_guard(self) -> Any:
        raise NotImplementedError

    async def forget_source_events(
        self,
        event_ids: Iterable[str],
        *,
        reason: str = "user_delete_event",
        persist_barrier: bool = True,
    ) -> int:
        """Invalidate affected skills and remove every user-visible derivative."""
        await self.initialize()
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return 0

        if persist_barrier:
            async with sqlite_connection_async(self.db_path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    created_at = time.time()
                    for offset in range(0, len(normalized), _EVENT_BATCH_SIZE):
                        await tombstone_source_event_ids(
                            db,
                            event_ids=normalized[offset : offset + _EVENT_BATCH_SIZE],
                            reason=reason,
                            created_at=created_at,
                        )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise

        invalidated = 0
        for offset in range(0, len(normalized), _EVENT_BATCH_SIZE):
            event_batch = normalized[offset : offset + _EVENT_BATCH_SIZE]
            last_skill_id = ""
            while True:
                skill_ids = await self._affected_skill_ids(
                    event_ids=event_batch,
                    after_skill_id=last_skill_id,
                    limit=_FORGET_BATCH_SIZE,
                )
                if not skill_ids:
                    break
                invalidated += await self._forget_skill_batch(skill_ids)
                last_skill_id = skill_ids[-1]
        return invalidated

    async def retire_governed_skill_identity(
        self,
        *,
        skill_name: str,
        skill_category: str,
    ) -> int:
        """Finish a prior failed cleanup before rebuilding the same skill identity."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                f"""
                SELECT skills.skill_id
                FROM procedural_skills AS skills
                WHERE skills.skill_name = ? AND skills.skill_category = ?
                  AND (
                      EXISTS (
                          SELECT 1
                          FROM {SKILL_EVENT_LINKS_TABLE} AS links
                          JOIN memory_source_event_tombstones AS tombstones
                            ON tombstones.event_id = links.event_id
                          WHERE links.skill_id = skills.skill_id
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM {SKILL_EVENT_LINKS_TABLE} AS links
                          JOIN memory_projection_blocks AS projection_blocks
                            ON projection_blocks.event_id = links.event_id
                           AND {source_event_derivation_block_predicate("projection_blocks")}
                          WHERE links.skill_id = skills.skill_id
                      )
                  )
                ORDER BY skills.skill_id
                LIMIT ?
                """,
                (skill_name, skill_category, _FORGET_BATCH_SIZE),
            ) as cursor:
                skill_ids = [str(row[0]) for row in await cursor.fetchall()]
        if not skill_ids:
            return 0
        return await self._forget_skill_batch(skill_ids)

    async def _affected_skill_ids(
        self,
        *,
        event_ids: tuple[str, ...],
        after_skill_id: str,
        limit: int,
    ) -> list[str]:
        placeholders = ", ".join("?" for _ in event_ids)
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                f"""
                SELECT DISTINCT links.skill_id
                FROM {SKILL_EVENT_LINKS_TABLE} AS links
                WHERE links.event_id IN ({placeholders})
                  AND links.skill_id > ?
                ORDER BY links.skill_id
                LIMIT ?
                """,
                (*event_ids, after_skill_id, max(1, int(limit))),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

    async def _forget_skill_batch(self, skill_ids: list[str]) -> int:
        if not skill_ids:
            return 0
        async with self.embedding_mutation_guard():
            if self._vector_index is not None:
                await self._delete_skill_vectors(skill_ids)
            return await self._scrub_skill_batch(skill_ids)

    async def _delete_skill_vectors(self, skill_ids: list[str]) -> None:
        last_entity_id = ""
        while True:
            entity_ids = await self._vector_entity_ids(
                skill_ids=skill_ids,
                after_entity_id=last_entity_id,
                limit=_VECTOR_ENTITY_BATCH_SIZE,
            )
            if not entity_ids:
                return
            for entity_id in entity_ids:
                await self._vector_index.delete_entity(entity_id=entity_id)
            last_entity_id = entity_ids[-1]

    async def _vector_entity_ids(
        self,
        *,
        skill_ids: list[str],
        after_entity_id: str,
        limit: int,
    ) -> list[str]:
        placeholders = ", ".join("?" for _ in skill_ids)
        async with sqlite_connection_async(self.db_path) as db:
            registry_exists = await _table_exists(db, "l4_skill_chunk_vectors")
            if registry_exists:
                query = f"""
                    SELECT chunk_id
                    FROM (
                        SELECT chunks.chunk_id
                        FROM {SKILL_CHUNKS_TABLE} AS chunks
                        WHERE chunks.skill_id IN ({placeholders})
                        UNION
                        SELECT vectors.chunk_id
                        FROM l4_skill_chunk_vectors AS vectors
                        WHERE {" OR ".join("instr(vectors.chunk_id, ?) = 1" for _ in skill_ids)}
                    )
                    WHERE chunk_id > ?
                    ORDER BY chunk_id
                    LIMIT ?
                """
                prefix_args = [f"{skill_id}::chunk-" for skill_id in skill_ids]
                args: tuple[Any, ...] = (
                    *skill_ids,
                    *prefix_args,
                    after_entity_id,
                    max(1, int(limit)),
                )
            else:
                query = f"""
                    SELECT chunks.chunk_id
                    FROM {SKILL_CHUNKS_TABLE} AS chunks
                    WHERE chunks.skill_id IN ({placeholders})
                      AND chunks.chunk_id > ?
                    ORDER BY chunks.chunk_id
                    LIMIT ?
                """
                args = (*skill_ids, after_entity_id, max(1, int(limit)))
            async with db.execute(query, args) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

    async def _scrub_skill_batch(self, skill_ids: list[str]) -> int:
        placeholders = ", ".join("?" for _ in skill_ids)
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM procedural_skills
                    WHERE skill_id IN ({placeholders}) AND deleted_at IS NULL
                    """,
                    tuple(skill_ids),
                ) as cursor:
                    row = await cursor.fetchone()
                newly_invalidated = int(row[0]) if row else 0
                await db.execute(
                    f"DELETE FROM l4_skills_fts WHERE skill_id IN ({placeholders})",
                    tuple(skill_ids),
                )
                await db.execute(
                    f"DELETE FROM {SKILL_CHUNKS_TABLE} WHERE skill_id IN ({placeholders})",
                    tuple(skill_ids),
                )
                await db.execute(
                    f"DELETE FROM {EXECUTION_TRACES_TABLE} WHERE skill_id IN ({placeholders})",
                    tuple(skill_ids),
                )
                await db.execute(
                    f"""
                    UPDATE procedural_skills
                    SET skill_name = '__forgotten__:' || skill_id,
                        skill_category = ?,
                        skill_type = ?,
                        proficiency = 0.0,
                        total_attempts = 0,
                        success_count = 0,
                        failure_count = 0,
                        success_rate = 0.0,
                        avg_execution_time_ms = NULL,
                        min_execution_time_ms = NULL,
                        max_execution_time_ms = NULL,
                        p95_execution_time_ms = NULL,
                        circuit_breaker_state = 'closed',
                        circuit_breaker_opened_at = NULL,
                        circuit_breaker_failure_count = 0,
                        circuit_breaker_success_count = 0,
                        optimized_prompt = NULL,
                        optimized_params = '{{}}',
                        optimization_score = NULL,
                        context_affinity = '{{}}',
                        source_event_ids = '[]',
                        last_used_at = NULL,
                        last_success_at = NULL,
                        last_failure_at = NULL,
                        embedding_status = 'disabled',
                        embedding_profile_id = NULL,
                        embedding_chunk_count = 0,
                        last_embedded_at = NULL,
                        pending_trace_count = 0,
                        deleted_at = COALESCE(deleted_at, ?),
                        updated_at = ?
                    WHERE skill_id IN ({placeholders})
                    """,
                    (
                        _FORGOTTEN_CATEGORY,
                        _FORGOTTEN_CATEGORY,
                        now,
                        now,
                        *skill_ids,
                    ),
                )
                await db.commit()
                return newly_invalidated
            except BaseException:
                await db.rollback()
                raise


async def _table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    async with db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ) as cursor:
        return await cursor.fetchone() is not None


__all__ = [
    "L4SourceEventGovernanceMixin",
    "SKILL_EVENT_LINKS_TABLE",
    "active_skill_predicate",
    "link_skill_source_event",
    "skill_accepts_source_event",
]
