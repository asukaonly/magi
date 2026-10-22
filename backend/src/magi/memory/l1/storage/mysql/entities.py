"""Manual and replaceable entity links with durable MySQL generation fencing."""

from __future__ import annotations

from .common import MysqlEventConnection
from .queries import MysqlEventQueries
from typing import cast

import time

from sqlalchemy import delete, func, insert, select, union_all, update

from magi.memory.entity_link_projection import (
    desired_entity_links_fingerprint,
    normalize_desired_entity_links,
)
from .common import identity
from . import schema as s


def effective_links():
    names = (
        "event_key",
        "entity_key",
        "event_id",
        "entity_id",
        "entity_type",
        "confidence",
        "created_at",
    )
    combined = union_all(
        *[
            select(*(table.c[name] for name in names))
            for table in (s.entities, s.projected_entities)
        ]
    ).subquery()
    return (
        select(
            combined.c.event_key,
            combined.c.entity_key,
            *[func.max(combined.c[name]).label(name) for name in names[2:]],
        )
        .group_by(combined.c.event_key, combined.c.entity_key)
        .subquery()
    )


class MysqlEventEntities(MysqlEventConnection):
    async def write_event_entities(
        self, mappings: list[tuple[str, str, str | None, float | None]]
    ) -> int:
        inserted = 0
        async with self._transaction(write=True) as connection:
            for event_id, entity_id, entity_type, confidence in mappings:
                keys = dict(event_key=identity(event_id), entity_key=identity(entity_id))
                exists = (
                    await connection.execute(
                        select(s.entities.c.event_key).where(
                            s.entities.c.event_key == keys["event_key"],
                            s.entities.c.entity_key == keys["entity_key"],
                        )
                    )
                ).first()
                if exists is None:
                    await connection.execute(
                        insert(s.entities).values(
                            **keys,
                            event_id=event_id,
                            entity_id=entity_id,
                            entity_type=entity_type,
                            confidence=confidence,
                            created_at=time.time(),
                        )
                    )
                    inserted += 1
        return inserted

    async def replace_projected_event_entities_batch(
        self,
        *,
        projections: list[
            tuple[str, int, str, int, int, list[tuple[str, str | None, float | None]]]
        ],
    ) -> bool:
        if not projections:
            return True
        normalized = []
        ids = set()
        for event_id, revision, token, attempts, generation, mappings in projections:
            event_id, token = str(event_id or "").strip(), str(token or "").strip()
            if not event_id or not token:
                raise ValueError("Event ID and lease token must not be empty")
            if event_id in ids:
                raise ValueError("Projected entity-link batch must contain unique event IDs")
            if int(revision) < 1 or int(attempts) < 1 or int(generation) < 0:
                raise ValueError("Invalid entity-link projection revision or generation")
            ids.add(event_id)
            links = normalize_desired_entity_links(mappings)
            normalized.append(
                (
                    event_id,
                    int(revision),
                    token,
                    int(attempts),
                    int(generation),
                    links,
                    desired_entity_links_fingerprint(links),
                )
            )
        generations = {item[4] for item in normalized}
        if len(generations) != 1:
            raise ValueError("Projected entity-link batch must use one clear generation")
        async with self._transaction(write=True) as connection:
            current_generation = (
                await connection.execute(
                    select(s.state.c.clear_generation).where(s.state.c.singleton_id == 1)
                )
            ).scalar_one()
            if current_generation != next(iter(generations)):
                return False
            current_by_event = {}
            for event_id, revision, token, attempts, generation, links, fingerprint in normalized:
                current = (
                    (
                        await connection.execute(
                            select(s.projection_state).where(
                                s.projection_state.c.event_key == identity(event_id)
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
                current_by_event[event_id] = current
                if (
                    current is not None
                    and current["revision"] == revision
                    and (
                        current["lease_token"] != token
                        or current["attempt_count"] != attempts
                        or current["payload_fingerprint"] != fingerprint
                    )
                ):
                    raise RuntimeError(
                        "L1 entity-link revision maps to conflicting projection payloads"
                    )
            for event_id, revision, token, attempts, generation, links, fingerprint in normalized:
                current = current_by_event[event_id]
                if current is not None and current["revision"] >= revision:
                    continue
                key, now = identity(event_id), time.time()
                values = dict(
                    revision=revision,
                    lease_token=token,
                    attempt_count=attempts,
                    payload_fingerprint=fingerprint,
                    applied_at=now,
                )
                await connection.execute(
                    delete(s.projected_entities).where(s.projected_entities.c.event_key == key)
                )
                if current is None:
                    await connection.execute(
                        insert(s.projection_state).values(
                            event_key=key, event_id=event_id, **values
                        )
                    )
                else:
                    await connection.execute(
                        update(s.projection_state)
                        .where(s.projection_state.c.event_key == key)
                        .values(**values)
                    )
                for entity_id, entity_type, confidence in links:
                    await connection.execute(
                        insert(s.projected_entities).values(
                            event_key=key,
                            entity_key=identity(entity_id),
                            event_id=event_id,
                            entity_id=entity_id,
                            entity_type=entity_type,
                            confidence=confidence,
                            revision=revision,
                            lease_token=token,
                            attempt_count=attempts,
                            created_at=now,
                        )
                    )
        return True

    async def align_entity_link_projection_clear_generation(self, clear_generation: int) -> int:
        generation = int(clear_generation)
        if generation < 0:
            raise ValueError("Clear generation must not be negative")
        async with self._transaction(write=True) as connection:
            current = (
                await connection.execute(
                    select(s.state.c.clear_generation).where(s.state.c.singleton_id == 1)
                )
            ).scalar_one()
            if generation < current:
                raise RuntimeError("L1 entity-link clear generation cannot move backwards")
            if generation == current:
                return 0
            count = (await connection.execute(delete(s.projected_entities))).rowcount
            await connection.execute(delete(s.projection_state))
            await connection.execute(
                update(s.state)
                .where(s.state.c.singleton_id == 1)
                .values(clear_generation=generation, updated_at=time.time())
            )
        return int(count)

    async def get_entity_event_ids(
        self, entity_ids: list[str], *, limit_per_entity: int = 20
    ) -> dict[str, list[str]]:
        links = effective_links()
        result = {}
        async with self._transaction() as connection:
            for entity_id in entity_ids:
                result[entity_id] = list(
                    (
                        await connection.execute(
                            select(links.c.event_id)
                            .where(
                                links.c.entity_key == identity(entity_id),
                                links.c.entity_id == entity_id,
                            )
                            .order_by(links.c.created_at.desc(), links.c.event_id)
                            .limit(limit_per_entity)
                        )
                    ).scalars()
                )
        return result

    async def get_event_entity_ids(self, event_ids: list[str]) -> dict[str, list[str]]:
        links = effective_links()
        result: dict[str, list[str]] = {key: [] for key in event_ids}
        async with self._transaction() as connection:
            for offset in range(0, len(event_ids), 500):
                page = event_ids[offset : offset + 500]
                rows = await connection.execute(
                    select(links.c.event_id, links.c.entity_id).where(
                        links.c.event_key.in_([identity(v) for v in page]),
                        links.c.event_id.in_(page),
                    )
                )
                for event_id, entity_id in rows:
                    result[event_id].append(entity_id)
        return result

    async def resolve_event_entities(self, event_ids: list[str]) -> list[str]:
        return list(
            dict.fromkeys(
                entity
                for values in (await self.get_event_entity_ids(event_ids)).values()
                for entity in values
            )
        )

    async def find_events_by_entities(
        self, entity_ids: list[str], *, exclude_event_ids: list[str] | None = None, limit: int = 30
    ) -> list[tuple[str, int]]:
        if not entity_ids:
            return []
        links = effective_links()
        query = select(
            func.max(links.c.event_id).label("event_id"), func.count().label("shared")
        ).where(
            links.c.entity_key.in_([identity(v) for v in entity_ids]),
            links.c.entity_id.in_(entity_ids),
        )
        if exclude_event_ids:
            query = query.where(links.c.event_key.not_in([identity(v) for v in exclude_event_ids]))
        query = (
            query.group_by(links.c.event_key)
            .order_by(func.count().desc(), func.max(links.c.event_id))
            .limit(limit)
        )
        async with self._transaction() as connection:
            return [(str(row.event_id), int(row.shared)) for row in await connection.execute(query)]

    async def expand_by_entities(
        self,
        seed_event_ids: list[str],
        *,
        limit: int = 30,
        exclude_event_ids: list[str] | None = None,
    ) -> list[str]:
        entities = await self.resolve_event_entities(seed_event_ids)
        rows = await self.find_events_by_entities(
            entities,
            exclude_event_ids=list(set(seed_event_ids) | set(exclude_event_ids or [])),
            limit=limit,
        )
        return [row[0] for row in rows]

    async def filter_ids_by_user(self, event_ids: list[str], user_id: str) -> list[str]:
        records = await cast(MysqlEventQueries, self)._records_by_ids(event_ids, active=True)
        return [
            key for key in event_ids if key in records and records[key].event.user_id == user_id
        ]
