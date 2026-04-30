"""ToM assertion retrieval helpers for the L2 cognition store."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .common import L2RetrievalQueryHostProtocol


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
        target_entity_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List ToM assertions ordered by recency."""
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
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))

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
        target_entity_id: Optional[str] = None,
        limit_per_entity: int = 100,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Batch-fetch assertions for multiple entities in one query."""
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
