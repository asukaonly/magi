"""Entity linkage helpers for the canonical L1 event store."""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Protocol, Tuple, cast

from ....core.sqlite import sqlite_connection_async


class _L1EventEntityHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...


class L1EventEntityMixin:
    """Maintain and query event/entity co-occurrence links."""

    async def write_event_entities(
        self,
        mappings: List[Tuple[str, str, Optional[str], Optional[float]]],
    ) -> int:
        """Persist (event_id, entity_id, entity_type, confidence) tuples.

        Duplicates are silently ignored via INSERT OR IGNORE.
        Returns the number of rows inserted.
        """
        if not mappings:
            return 0
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        now = time.time()
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            await db.executemany(
                "INSERT OR IGNORE INTO l1_event_entities"
                " (event_id, entity_id, entity_type, confidence, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [(eid, entid, etype, conf, now) for eid, entid, etype, conf in mappings],
            )
            await db.commit()
            return int(db.total_changes)

    async def get_entity_event_ids(
        self,
        entity_ids: List[str],
        *,
        limit_per_entity: int = 20,
    ) -> Dict[str, List[str]]:
        """Return event IDs associated with each entity.

        Returns ``{entity_id: [event_id, ...]}`` with the most recent
        events first (by created_at DESC), capped at *limit_per_entity*.
        """
        if not entity_ids:
            return {}
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        result: Dict[str, List[str]] = {eid: [] for eid in entity_ids}
        async with sqlite_connection_async(host.db_path) as db:
            for entity_id in entity_ids:
                async with db.execute(
                    "SELECT event_id FROM l1_event_entities"
                    " WHERE entity_id = ?"
                    " ORDER BY created_at DESC"
                    " LIMIT ?",
                    (entity_id, limit_per_entity),
                ) as cursor:
                    rows = await cursor.fetchall()
                result[entity_id] = [row[0] for row in rows]
        return result

    async def get_event_entity_ids(
        self,
        event_ids: List[str],
    ) -> Dict[str, List[str]]:
        """Return entity IDs for each event.

        Returns ``{event_id: [entity_id, ...]}`` for all given events.
        """
        if not event_ids:
            return {}
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        result: Dict[str, List[str]] = {eid: [] for eid in event_ids}
        async with sqlite_connection_async(host.db_path) as db:
            placeholders = ", ".join("?" for _ in event_ids)
            async with db.execute(
                f"SELECT event_id, entity_id FROM l1_event_entities WHERE event_id IN ({placeholders})",
                tuple(event_ids),
            ) as cursor:
                for row in await cursor.fetchall():
                    result.setdefault(row[0], []).append(row[1])
        return result

    async def expand_by_entities(
        self,
        seed_event_ids: List[str],
        *,
        limit: int = 30,
        exclude_event_ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Find events that share entities with *seed_event_ids*.

        Returns event IDs ordered by the number of shared entities (desc).
        """
        if not seed_event_ids:
            return []
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        exclude = set(exclude_event_ids or []) | set(seed_event_ids)

        async with sqlite_connection_async(host.db_path) as db:
            placeholders = ", ".join("?" for _ in seed_event_ids)
            async with db.execute(
                f"SELECT DISTINCT entity_id FROM l1_event_entities WHERE event_id IN ({placeholders})",
                tuple(seed_event_ids),
            ) as cursor:
                entity_ids = [row[0] for row in await cursor.fetchall()]

            if not entity_ids:
                return []

            entity_placeholders = ", ".join("?" for _ in entity_ids)
            async with db.execute(
                f"SELECT event_id, COUNT(DISTINCT entity_id) AS shared"
                f" FROM l1_event_entities"
                f" WHERE entity_id IN ({entity_placeholders})"
                f" GROUP BY event_id"
                f" ORDER BY shared DESC"
                f" LIMIT ?",
                (*entity_ids, limit + len(exclude)),
            ) as cursor:
                rows = await cursor.fetchall()

        return [row[0] for row in rows if row[0] not in exclude][:limit]

    async def resolve_event_entities(self, event_ids: List[str]) -> List[str]:
        """Return distinct entity IDs linked to the given events."""
        if not event_ids:
            return []
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            placeholders = ", ".join("?" for _ in event_ids)
            async with db.execute(
                f"SELECT DISTINCT entity_id FROM l1_event_entities WHERE event_id IN ({placeholders})",
                tuple(event_ids),
            ) as cursor:
                return [row[0] for row in await cursor.fetchall()]

    async def find_events_by_entities(
        self,
        entity_ids: List[str],
        *,
        exclude_event_ids: Optional[List[str]] = None,
        limit: int = 30,
    ) -> List[Tuple[str, int]]:
        """Find events sharing given entities, ranked by shared-entity count.

        Returns ``[(event_id, shared_count), ...]`` ordered desc by *shared_count*.
        """
        if not entity_ids:
            return []
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        exclude = set(exclude_event_ids or [])
        entity_placeholders = ", ".join("?" for _ in entity_ids)
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(
                f"SELECT event_id, COUNT(DISTINCT entity_id) AS shared"
                f" FROM l1_event_entities"
                f" WHERE entity_id IN ({entity_placeholders})"
                f" GROUP BY event_id"
                f" ORDER BY shared DESC"
                f" LIMIT ?",
                (*entity_ids, limit + len(exclude)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows if row[0] not in exclude][:limit]

    async def filter_ids_by_user(self, event_ids: List[str], user_id: str) -> List[str]:
        """Return the subset of *event_ids* that belong to *user_id*."""
        if not event_ids:
            return []
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        placeholders = ", ".join("?" for _ in event_ids)
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(
                f"SELECT event_id FROM fact_events"
                f" WHERE event_id IN ({placeholders}) AND user_id = ? AND deleted_at IS NULL",
                (*event_ids, user_id),
            ) as cursor:
                rows = await cursor.fetchall()
        valid = {str(row[0]) for row in rows}
        return [event_id for event_id in event_ids if event_id in valid]
