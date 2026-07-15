"""ToM snapshot retrieval helpers for the L2 cognition store."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...sql_search import build_like_search_clause
from .common import L2RetrievalQueryHostProtocol


class L2StoreSnapshotQueryMixin:
    """Read and batch-query materialized ToM snapshots."""

    async def get_tom_snapshot(self, *, entity_id: str, entity_type: str) -> Optional[Dict[str, Any]]:
        """Fetch the current stable snapshot for an entity."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT snapshot.*
                FROM tom_snapshots AS snapshot
                LEFT JOIN memory_subject_revisions AS revision
                  ON revision.subject_key = snapshot.entity_id
                JOIN memory_clear_state AS clear_state
                  ON clear_state.singleton_id = 1
                WHERE snapshot.entity_id = ? AND snapshot.entity_type = ?
                  AND snapshot.source_revision = COALESCE(revision.revision, 0)
                  AND snapshot.source_generation = clear_state.generation
                """,
                (entity_id, entity_type),
            ) as cursor:
                row = await cursor.fetchone()
        return host._snapshot_row_to_dict(row) if row else None

    async def count_tom_snapshots(self, *, query: str | None = None) -> int:
        """Count all ToM snapshots."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        sql = """
            SELECT COUNT(*)
            FROM tom_snapshots AS snapshot
            LEFT JOIN memory_subject_revisions AS revision
              ON revision.subject_key = snapshot.entity_id
            JOIN memory_clear_state AS clear_state
              ON clear_state.singleton_id = 1
            WHERE snapshot.source_revision = COALESCE(revision.revision, 0)
              AND snapshot.source_generation = clear_state.generation
        """
        args: list[Any] = []
        search_sql, search_args = build_like_search_clause(
            [
                "snapshot_id",
                "entity_id",
                "entity_type",
                "core_traits",
                "sensitive_triggers",
                "preferences",
                "public_sentiment_profile",
                "relationship_topology",
                "current_context",
                "current_mood",
                "update_source_assertion_ids",
                "core_traits_history",
                "preferences_history",
                "relationship_history",
                "active_record_ids",
                "superseded_record_ids",
                "emerging_signals",
                "mood_trajectory",
            ],
            query,
        )
        sql += search_sql
        args.extend(search_args)
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(sql, tuple(args)) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_tom_snapshots(
        self,
        *,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        query: str | None = None,
    ) -> List[Dict[str, Any]]:
        """List materialized ToM snapshots ordered by recency."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        search_query = query
        query = """
            SELECT snapshot.*
            FROM tom_snapshots AS snapshot
            LEFT JOIN memory_subject_revisions AS revision
              ON revision.subject_key = snapshot.entity_id
            JOIN memory_clear_state AS clear_state
              ON clear_state.singleton_id = 1
            WHERE snapshot.source_revision = COALESCE(revision.revision, 0)
              AND snapshot.source_generation = clear_state.generation
        """
        args: list[Any] = []
        if entity_id:
            query += " AND entity_id = ?"
            args.append(entity_id)
        if entity_type:
            query += " AND entity_type = ?"
            args.append(entity_type)
        search_sql, search_args = build_like_search_clause(
            [
                "snapshot_id",
                "entity_id",
                "entity_type",
                "core_traits",
                "sensitive_triggers",
                "preferences",
                "public_sentiment_profile",
                "relationship_topology",
                "current_context",
                "current_mood",
                "update_source_assertion_ids",
                "core_traits_history",
                "preferences_history",
                "relationship_history",
                "active_record_ids",
                "superseded_record_ids",
                "emerging_signals",
                "mood_trajectory",
            ],
            search_query,
        )
        query += search_sql
        args.extend(search_args)
        query += " ORDER BY last_updated_at DESC LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [host._snapshot_row_to_dict(row) for row in rows]

    async def batch_get_tom_snapshots(
        self,
        *,
        entities: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """Batch-fetch snapshots for multiple entity_id+entity_type pairs."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        if not entities:
            return []

        conditions: list[str] = []
        args: list[Any] = []
        for entity in entities:
            conditions.append("(entity_id = ? AND entity_type = ?)")
            args.append(str(entity["entity_id"]))
            args.append(str(entity["entity_type"]))

        query = f"""
            SELECT snapshot.*
            FROM tom_snapshots AS snapshot
            LEFT JOIN memory_subject_revisions AS revision
              ON revision.subject_key = snapshot.entity_id
            JOIN memory_clear_state AS clear_state
              ON clear_state.singleton_id = 1
            WHERE ({' OR '.join(conditions)})
              AND snapshot.source_revision = COALESCE(revision.revision, 0)
              AND snapshot.source_generation = clear_state.generation
        """
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [host._snapshot_row_to_dict(row) for row in rows]
