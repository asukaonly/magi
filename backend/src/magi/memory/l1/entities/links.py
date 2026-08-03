"""Entity linkage helpers for the canonical L1 event store."""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Protocol, Tuple, cast

from ....core.sqlite import sqlite_connection_async
from ...entity_link_projection import (
    desired_entity_links_fingerprint,
    normalize_desired_entity_links,
)

_EFFECTIVE_EVENT_ENTITIES = "l1_effective_event_entities"


class _L1EventEntityHostProtocol(Protocol):
    db_path: str
    _entity_link_clear_generation: int | None

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

    async def replace_projected_event_entities(
        self,
        *,
        event_id: str,
        revision: int,
        lease_token: str,
        attempt_count: int,
        clear_generation: int,
        mappings: List[Tuple[str, Optional[str], Optional[float]]],
    ) -> bool:
        """Publish one revision-fenced L2 entity-link projection."""

        return await self.replace_projected_event_entities_batch(
            projections=[
                (
                    event_id,
                    revision,
                    lease_token,
                    attempt_count,
                    clear_generation,
                    mappings,
                )
            ]
        )

    async def replace_projected_event_entities_batch(
        self,
        *,
        projections: List[
            Tuple[
                str,
                int,
                str,
                int,
                int,
                List[Tuple[str, Optional[str], Optional[float]]],
            ]
        ],
    ) -> bool:
        """Atomically publish a complete multi-event L2 projection batch.

        The legacy ``l1_event_entities`` table remains manual/append-only.
        L2 owns a separate replaceable projection so replay can remove links
        without deleting a matching manual link.
        """

        if not projections:
            return True
        normalized: list[
            tuple[
                str,
                int,
                str,
                int,
                int,
                dict[str, tuple[Optional[str], Optional[float]]],
                str,
            ]
        ] = []
        event_ids: set[str] = set()
        for (
            event_id,
            revision,
            lease_token,
            attempt_count,
            clear_generation,
            mappings,
        ) in projections:
            normalized_event_id = str(event_id or "").strip()
            normalized_lease_token = str(lease_token or "").strip()
            normalized_revision = int(revision)
            normalized_attempt_count = int(attempt_count)
            normalized_clear_generation = int(clear_generation)
            if not normalized_event_id:
                raise ValueError("event_id must not be empty")
            if normalized_event_id in event_ids:
                raise ValueError("projected entity-link batch must contain unique event IDs")
            event_ids.add(normalized_event_id)
            if not normalized_lease_token:
                raise ValueError("lease_token must not be empty")
            if normalized_revision < 1:
                raise ValueError("revision must be positive")
            if normalized_attempt_count < 1:
                raise ValueError("attempt_count must be positive")
            if normalized_clear_generation < 0:
                raise ValueError("clear_generation must not be negative")
            normalized_links = normalize_desired_entity_links(mappings)
            normalized_mappings = {
                entity_id: (entity_type, confidence)
                for entity_id, entity_type, confidence in normalized_links
            }
            normalized.append(
                (
                    normalized_event_id,
                    normalized_revision,
                    normalized_lease_token,
                    normalized_attempt_count,
                    normalized_clear_generation,
                    normalized_mappings,
                    desired_entity_links_fingerprint(normalized_links),
                )
            )

        host = cast(_L1EventEntityHostProtocol, self)
        clear_generations = {projection[4] for projection in normalized}
        if len(clear_generations) != 1:
            raise ValueError("projected entity-link batch must use one clear generation")
        incoming_clear_generation = next(iter(clear_generations))
        if (
            host._entity_link_clear_generation is not None
            and host._entity_link_clear_generation != incoming_clear_generation
        ):
            return False
        await host.initialize()
        now = time.time()
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    """
                    SELECT clear_generation
                    FROM l1_entity_link_projection_generation
                    WHERE singleton_id = 1
                    """
                ) as cursor:
                    generation_row = await cursor.fetchone()
                if generation_row is None:
                    raise RuntimeError("L1 entity-link projection generation is missing")
                current_clear_generation = int(generation_row[0])
                host._entity_link_clear_generation = current_clear_generation
                if current_clear_generation != incoming_clear_generation:
                    await db.rollback()
                    return False
                current_by_event: dict[str, tuple | None] = {}
                for (
                    normalized_event_id,
                    normalized_revision,
                    normalized_lease_token,
                    normalized_attempt_count,
                    _normalized_clear_generation,
                    _normalized_mappings,
                    payload_fingerprint,
                ) in normalized:
                    async with db.execute(
                        """
                        SELECT revision, lease_token, attempt_count, payload_fingerprint
                        FROM l1_event_entity_projection_state
                        WHERE event_id = ?
                        """,
                        (normalized_event_id,),
                    ) as cursor:
                        current = await cursor.fetchone()
                    current_by_event[normalized_event_id] = current
                    if current is not None and int(current[0]) == normalized_revision and (
                        str(current[1]) != normalized_lease_token
                        or int(current[2]) != normalized_attempt_count
                        or str(current[3]) != payload_fingerprint
                    ):
                        raise RuntimeError(
                            "L1 entity-link revision maps to conflicting projection payloads"
                        )

                for (
                    normalized_event_id,
                    normalized_revision,
                    normalized_lease_token,
                    normalized_attempt_count,
                    _normalized_clear_generation,
                    normalized_mappings,
                    payload_fingerprint,
                ) in normalized:
                    current = current_by_event[normalized_event_id]
                    if current is not None and int(current[0]) >= normalized_revision:
                        continue
                    if current is None:
                        await db.execute(
                            """
                            INSERT INTO l1_event_entity_projection_state(
                                event_id, revision, lease_token, attempt_count,
                                payload_fingerprint, applied_at
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                normalized_event_id,
                                normalized_revision,
                                normalized_lease_token,
                                normalized_attempt_count,
                                payload_fingerprint,
                                now,
                            ),
                        )
                    else:
                        await db.execute(
                            "DELETE FROM l1_projected_event_entities WHERE event_id = ?",
                            (normalized_event_id,),
                        )
                        await db.execute(
                            """
                            UPDATE l1_event_entity_projection_state
                            SET revision = ?, lease_token = ?, attempt_count = ?,
                                payload_fingerprint = ?, applied_at = ?
                            WHERE event_id = ? AND revision < ?
                            """,
                            (
                                normalized_revision,
                                normalized_lease_token,
                                normalized_attempt_count,
                                payload_fingerprint,
                                now,
                                normalized_event_id,
                                normalized_revision,
                            ),
                        )

                    if normalized_mappings:
                        await db.executemany(
                            """
                            INSERT INTO l1_projected_event_entities(
                                event_id, entity_id, entity_type, confidence,
                                revision, lease_token, attempt_count, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            [
                                (
                                    normalized_event_id,
                                    entity_id,
                                    entity_type,
                                    confidence,
                                    normalized_revision,
                                    normalized_lease_token,
                                    normalized_attempt_count,
                                    now,
                                )
                                for entity_id, (entity_type, confidence) in sorted(
                                    normalized_mappings.items()
                                )
                            ],
                        )
                await db.commit()
                return True
            except BaseException:
                await db.rollback()
                raise

    async def align_entity_link_projection_clear_generation(
        self,
        clear_generation: int,
    ) -> int:
        """Fence old appliers and clear stale projected links atomically."""

        normalized_generation = int(clear_generation)
        if normalized_generation < 0:
            raise ValueError("clear_generation must not be negative")
        host = cast(_L1EventEntityHostProtocol, self)
        if (
            host._entity_link_clear_generation is None
            or normalized_generation > host._entity_link_clear_generation
        ):
            host._entity_link_clear_generation = normalized_generation
        await host.initialize()
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    """
                    SELECT clear_generation
                    FROM l1_entity_link_projection_generation
                    WHERE singleton_id = 1
                    """
                ) as cursor:
                    row = await cursor.fetchone()
                current_generation = int(row[0]) if row is not None else -1
                if current_generation > normalized_generation:
                    host._entity_link_clear_generation = current_generation
                    raise RuntimeError("L1 entity-link clear generation cannot move backwards")
                if current_generation == normalized_generation:
                    await db.commit()
                    return 0
                async with db.execute(
                    "SELECT COUNT(*) FROM l1_projected_event_entities"
                ) as cursor:
                    count_row = await cursor.fetchone()
                removed = int(count_row[0]) if count_row else 0
                await db.execute("DELETE FROM l1_event_entity_projection_state")
                await db.execute(
                    """
                    UPDATE l1_entity_link_projection_generation
                    SET clear_generation = ?, updated_at = ?
                    WHERE singleton_id = 1 AND clear_generation < ?
                    """,
                    (normalized_generation, time.time(), normalized_generation),
                )
                await db.commit()
                return removed
            except BaseException:
                await db.rollback()
                raise

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
                    f"SELECT event_id FROM {_EFFECTIVE_EVENT_ENTITIES}"
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
                f"SELECT event_id, entity_id FROM {_EFFECTIVE_EVENT_ENTITIES} "
                f"WHERE event_id IN ({placeholders})",
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
                f"SELECT DISTINCT entity_id FROM {_EFFECTIVE_EVENT_ENTITIES} "
                f"WHERE event_id IN ({placeholders})",
                tuple(seed_event_ids),
            ) as cursor:
                entity_ids = [row[0] for row in await cursor.fetchall()]

            if not entity_ids:
                return []

            entity_placeholders = ", ".join("?" for _ in entity_ids)
            async with db.execute(
                f"SELECT event_id, COUNT(DISTINCT entity_id) AS shared"
                f" FROM {_EFFECTIVE_EVENT_ENTITIES}"
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
                f"SELECT DISTINCT entity_id FROM {_EFFECTIVE_EVENT_ENTITIES} "
                f"WHERE event_id IN ({placeholders})",
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
                f" FROM {_EFFECTIVE_EVENT_ENTITIES}"
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
