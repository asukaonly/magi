"""ToM assertion retrieval helpers for the L2 cognition store."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..assertions.state_machine import RETRIEVAL_EXCLUDED_STATUSES
from .common import L2RetrievalQueryHostProtocol


def _excluded_status_clause() -> tuple[str, list[str]]:
    """SQL fragment + params excluding forget/reject governance statuses."""
    placeholders = ", ".join("?" for _ in RETRIEVAL_EXCLUDED_STATUSES)
    return f" AND status NOT IN ({placeholders})", list(RETRIEVAL_EXCLUDED_STATUSES)


class L2StoreAssertionQueryMixin:
    """Read and batch-query ToM assertions."""

    async def count_tom_assertions(self) -> int:
        """Count all ToM assertions."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM tom_trait_assertions") as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_tom_assertions(
        self,
        *,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        trait_families: Optional[List[str]] = None,
        validation_states: Optional[List[str]] = None,
        include_expired: bool = True,
        include_inactive: bool = False,
        target_entity_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        temporal_clause: Optional[tuple[str, list[Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """List ToM assertions ordered by recency.

        By default forgotten/rejected records (``status`` in the governance set)
        are excluded; pass ``include_inactive=True`` for admin/debug reads.
        """
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        query = "SELECT * FROM tom_trait_assertions WHERE 1=1"
        args: list[Any] = []
        if entity_id:
            query += " AND entity_id = ?"
            args.append(entity_id)
        if entity_type:
            query += " AND entity_type = ?"
            args.append(entity_type)
        if trait_families:
            placeholders = ", ".join("?" for _ in trait_families)
            query += f" AND trait_family IN ({placeholders})"
            args.extend([str(item).strip().lower() for item in trait_families])
        if validation_states:
            placeholders = ", ".join("?" for _ in validation_states)
            query += f" AND validation_state IN ({placeholders})"
            args.extend([str(item).strip() for item in validation_states])
        if target_entity_id:
            query += " AND target_entity_id = ?"
            args.append(target_entity_id)
        if not include_expired:
            now = time.time()
            query += " AND (expires_at IS NULL OR expires_at > ?)"
            args.append(now)
        if not include_inactive:
            status_sql, status_args = _excluded_status_clause()
            query += status_sql
            args.extend(status_args)
        if temporal_clause:
            tc_sql, tc_params = temporal_clause
            if tc_sql:
                query += f" AND {tc_sql}"
                args.extend(tc_params)
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [host._assertion_row_to_dict(row) for row in rows]

    async def list_assertions_for_episode(
        self,
        *,
        episode_id: str,
        limit: int = 100,
        event_limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """List live assertions inferred from events in an episode.

        The link is derived, not stored: an assertion belongs to an episode when
        its ``evidence_events`` JSON array overlaps the episode's membership
        rows. Keep the event-id set bounded so this query stays a detail-page
        lookup instead of becoming an unbounded scan.
        """
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()

        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(
                """
                SELECT event_id
                FROM episode_events
                WHERE episode_id = ?
                ORDER BY added_at ASC
                LIMIT ?
                """,
                (episode_id, int(event_limit)),
            ) as cursor:
                event_rows = await cursor.fetchall()

        event_ids = [str(row[0]) for row in event_rows if row and row[0]]
        if not event_ids:
            return []

        event_placeholders = ", ".join("?" for _ in event_ids)
        status_sql, status_args = _excluded_status_clause()
        query = f"""
            SELECT DISTINCT a.*
            FROM tom_trait_assertions AS a
            JOIN json_each(a.evidence_events) AS evidence
              ON evidence.value IN ({event_placeholders})
            WHERE 1=1
            {status_sql}
            ORDER BY a.updated_at DESC
            LIMIT ?
        """
        args: list[Any] = [*event_ids, *status_args, int(limit)]

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [host._assertion_row_to_dict(row) for row in rows]

    async def expire_session_decay_assertions(
        self,
        *,
        entity_ids: List[str],
    ) -> int:
        """Mark tentative session-decay assertions as expired for the given entities."""
        if not entity_ids:
            return 0
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        now = time.time()
        placeholders = ", ".join("?" for _ in entity_ids)
        async with sqlite_connection_async(host.db_path) as db:
            cursor = await db.execute(
                f"""
                UPDATE tom_trait_assertions
                SET validation_state = 'expired', status = 'expired',
                    expires_at = ?, updated_at = ?
                WHERE entity_id IN ({placeholders})
                  AND decay_policy = 'session_decay'
                  AND validation_state = 'tentative'
                """,
                (now, now, *entity_ids),
            )
            count = int(cursor.rowcount)
            await db.commit()
        return count

    async def list_assertions_by_status(
        self,
        status: str,
        *,
        entity_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Return all assertion rows with the given ``status`` value.

        This is a low-level admin/maintenance query that bypasses the normal
        ``RETRIEVAL_EXCLUDED_STATUSES`` filter intentionally — for example, to
        fetch ``status='shadow'`` rows that the normal read path hides.
        """
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        query = "SELECT * FROM tom_trait_assertions WHERE status = ?"
        args: list[Any] = [status]
        if entity_id:
            query += " AND entity_id = ?"
            args.append(entity_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(int(limit))
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [host._assertion_row_to_dict(row) for row in rows]

    async def get_tom_assertion(self, *, assertion_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one ToM assertion by id."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        async with aiosqlite.connect(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
                (assertion_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return host._assertion_row_to_dict(row) if row else None

    async def batch_list_tom_assertions(
        self,
        *,
        entity_ids: List[str],
        entity_type: Optional[str] = None,
        trait_families: Optional[List[str]] = None,
        validation_states: Optional[List[str]] = None,
        include_expired: bool = False,
        include_inactive: bool = False,
        target_entity_id: Optional[str] = None,
        limit_per_entity: int = 100,
        temporal_clause: Optional[tuple[str, list[Any]]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Batch-fetch assertions for multiple entities in one query.

        Forgotten/rejected records are excluded by default; pass
        ``include_inactive=True`` for admin/debug reads.
        """
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        if not entity_ids:
            return {}

        unique_ids = list(dict.fromkeys(entity_ids))
        id_placeholders = ", ".join("?" for _ in unique_ids)
        query = f"SELECT * FROM tom_trait_assertions WHERE entity_id IN ({id_placeholders})"
        args: list[Any] = list(unique_ids)

        if entity_type:
            query += " AND entity_type = ?"
            args.append(entity_type)
        if trait_families:
            tf_ph = ", ".join("?" for _ in trait_families)
            query += f" AND trait_family IN ({tf_ph})"
            args.extend(str(tf).strip().lower() for tf in trait_families)
        if validation_states:
            vs_ph = ", ".join("?" for _ in validation_states)
            query += f" AND validation_state IN ({vs_ph})"
            args.extend(str(vs).strip() for vs in validation_states)
        if target_entity_id:
            query += " AND target_entity_id = ?"
            args.append(target_entity_id)
        if not include_expired:
            now = time.time()
            query += " AND (expires_at IS NULL OR expires_at > ?)"
            args.append(now)
        if not include_inactive:
            status_sql, status_args = _excluded_status_clause()
            query += status_sql
            args.extend(status_args)
        if temporal_clause:
            tc_sql, tc_params = temporal_clause
            if tc_sql:
                query += f" AND {tc_sql}"
                args.extend(tc_params)
        query += " ORDER BY updated_at DESC"

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        result: Dict[str, List[Dict[str, Any]]] = {eid: [] for eid in unique_ids}
        for row in rows:
            assertion = host._assertion_row_to_dict(row)
            eid = assertion["entity_id"]
            if eid in result and len(result[eid]) < limit_per_entity:
                result[eid].append(assertion)
        return result
