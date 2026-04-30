"""ToM snapshot retrieval helpers for the L2 cognition store."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
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
                "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                (entity_id, entity_type),
            ) as cursor:
                row = await cursor.fetchone()
        return host._snapshot_row_to_dict(row) if row else None

    async def count_tom_snapshots(self) -> int:
        """Count all ToM snapshots."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM tom_snapshots") as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_tom_snapshots(
        self,
        *,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List materialized ToM snapshots ordered by recency."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        query = "SELECT * FROM tom_snapshots WHERE 1=1"
        args: list[Any] = []
        if entity_id:
            query += " AND entity_id = ?"
            args.append(entity_id)
        if entity_type:
            query += " AND entity_type = ?"
            args.append(entity_type)
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

        query = f"SELECT * FROM tom_snapshots WHERE {' OR '.join(conditions)}"
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [host._snapshot_row_to_dict(row) for row in rows]
