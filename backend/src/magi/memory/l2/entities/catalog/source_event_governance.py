"""Entity alias and vector cleanup for forgotten source events."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any, Protocol, cast

from .....core.sqlite import sqlite_connection_async
from ....source_event_governance import normalize_source_event_ids


class _EntitySourceEventGovernanceHost(Protocol):
    db_path: str
    _vector_index: Any

    async def initialize(self) -> None: ...

    async def _maybe_embed_entity(self, entity_id: str) -> bool: ...

    def _entity_vector_write_lock(self) -> Any: ...


class L2EntitySourceEventGovernanceMixin:
    """Fail closed around alias rebuilds that change entity embedding text."""

    async def forget_entity_catalog(
        self,
        entity_id: str,
        *,
        operation_id: str | None = None,
    ) -> dict[str, int]:
        """Remove one user-forgotten entity from every catalog surface."""
        host = cast(_EntitySourceEventGovernanceHost, self)
        await host.initialize()
        normalized_entity_id = str(entity_id or "").strip()
        if not normalized_entity_id:
            raise ValueError("entity_id must not be empty")
        if host._vector_index is None:
            return await self._delete_entity_catalog_rows(
                host,
                entity_id=normalized_entity_id,
                operation_id=operation_id,
            )
        async with host._entity_vector_write_lock():
            await host._vector_index.delete_entity(entity_id=normalized_entity_id)
            return await self._delete_entity_catalog_rows(
                host,
                entity_id=normalized_entity_id,
                operation_id=operation_id,
            )

    async def _delete_entity_catalog_rows(
        self,
        host: _EntitySourceEventGovernanceHost,
        *,
        entity_id: str,
        operation_id: str | None,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        async with sqlite_connection_async(host.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                if operation_id is not None:
                    await self._snapshot_blocked_identities_before_delete(
                        db,
                        operation_id=str(operation_id),
                        entity_id=entity_id,
                    )
                for key, table, where in (
                    ("entity_name_evidence", "entity_name_evidence", "entity_id = ?"),
                    ("entity_aliases", "entity_aliases", "entity_id = ?"),
                    (
                        "entity_mentions",
                        "entity_mentions",
                        "resolved_entity_id = ?",
                    ),
                    ("entity_catalog", "entity_catalog", "entity_id = ?"),
                ):
                    cursor = await db.execute(
                        f"DELETE FROM {table} WHERE {where}",
                        (entity_id,),
                    )
                    counts[key] = max(int(cursor.rowcount), 0)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return counts

    @staticmethod
    async def _snapshot_blocked_identities_before_delete(
        db: Any,
        *,
        operation_id: str,
        entity_id: str,
    ) -> None:
        """Atomically retain final catalog names for every blocked source event."""
        async with db.execute(
            """
            SELECT surface, entity_type FROM (
                SELECT canonical_name AS surface, entity_type
                FROM entity_catalog
                WHERE entity_id = ?
                UNION
                SELECT alias.normalized_alias AS surface, catalog.entity_type
                FROM entity_aliases AS alias
                JOIN entity_catalog AS catalog ON catalog.entity_id = alias.entity_id
                WHERE alias.entity_id = ?
            )
            """,
            (entity_id, entity_id),
        ) as cursor:
            rows = await cursor.fetchall()
        identities = {
            (str(row[0] or "").strip().casefold(), str(row[1] or "").strip())
            for row in rows
            if str(row[0] or "").strip()
        }
        if not identities:
            return
        created_at = time.time()
        for normalized_surface, entity_type in identities:
            await db.execute(
                """
                INSERT OR IGNORE INTO memory_entity_projection_identity_blocks(
                    target_id, event_id, normalized_surface, entity_type,
                    operation_id, created_at
                )
                SELECT candidate.target_id, candidate.event_id, ?, ?, ?, ?
                FROM memory_projection_blocks AS candidate
                WHERE candidate.block_kind IN (
                    'entity_projection', 'entity_projection_candidate'
                )
                  AND candidate.target_id = ?
                """,
                (
                    normalized_surface,
                    entity_type,
                    operation_id,
                    created_at,
                    entity_id,
                ),
            )

    async def prepare_source_event_forgetting(
        self,
        event_ids: Iterable[str],
    ) -> tuple[str, ...]:
        """Delete existing vectors before aliases derived from events are rebuilt."""
        host = cast(_EntitySourceEventGovernanceHost, self)
        await host.initialize()
        entity_ids = await self._source_event_entity_ids(event_ids)
        if host._vector_index is not None:
            for entity_id in entity_ids:
                await host._vector_index.delete_entity(entity_id=entity_id)
        return entity_ids

    async def finish_source_event_forgetting(
        self,
        prepared_entity_ids: Iterable[str],
        *,
        updated_after: float,
    ) -> int:
        """Delete raced vectors and rebuild embeddings from the retained aliases."""
        host = cast(_EntitySourceEventGovernanceHost, self)
        await host.initialize()
        entity_ids = set(normalize_source_event_ids(prepared_entity_ids))
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(
                """
                SELECT entity_id
                FROM entity_catalog
                WHERE embedding_status = 'pending' AND updated_at >= ?
                ORDER BY entity_id
                """,
                (float(updated_after),),
            ) as cursor:
                entity_ids.update(str(row[0]) for row in await cursor.fetchall())
        if not entity_ids:
            return 0
        if host._vector_index is not None:
            for entity_id in sorted(entity_ids):
                await host._vector_index.delete_entity(entity_id=entity_id)
        rebuilt = 0
        for entity_id in sorted(entity_ids):
            rebuilt += int(await host._maybe_embed_entity(entity_id))
        return rebuilt

    async def _source_event_entity_ids(
        self,
        event_ids: Iterable[str],
    ) -> tuple[str, ...]:
        host = cast(_EntitySourceEventGovernanceHost, self)
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return ()
        event_json = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(
                """
                SELECT entity_id
                FROM (
                    SELECT DISTINCT resolved_entity_id AS entity_id
                    FROM entity_mentions AS mention
                    WHERE resolved_entity_id IS NOT NULL
                      AND TRIM(resolved_entity_id) != ''
                      AND EXISTS (
                          SELECT 1
                          FROM json_each(CASE
                              WHEN json_valid(mention.evidence_event_ids)
                                  THEN mention.evidence_event_ids
                              ELSE '[]'
                          END) AS evidence
                          WHERE TRIM(CAST(evidence.value AS TEXT)) IN (
                              SELECT CAST(value AS TEXT) FROM json_each(?)
                          )
                      )
                    UNION
                    SELECT DISTINCT entity_id
                    FROM entity_name_evidence
                    WHERE event_id IN (
                        SELECT CAST(value AS TEXT) FROM json_each(?)
                    )
                )
                ORDER BY entity_id
                """,
                (event_json, event_json),
            ) as cursor:
                return tuple(str(row[0]) for row in await cursor.fetchall())


__all__ = ["L2EntitySourceEventGovernanceMixin"]
