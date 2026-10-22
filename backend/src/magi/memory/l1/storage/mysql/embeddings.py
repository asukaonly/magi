"""Source-checked embedding publication in the MySQL event transaction."""

from __future__ import annotations

from .common import MysqlEventConnection

import time

from sqlalchemy import delete, func, insert, select, update

from magi.memory.event_contracts import MemoryDomain, MemoryEvent
from ...embedding_contracts import EventChunkRecord, EventEmbeddingPublication, EventEmbeddingSource
from ...embeddings.common import EmbeddingStatus, embedding_status_code
from .common import identity, record
from . import schema as s


class MysqlEventEmbeddings(MysqlEventConnection):
    async def count_pending_embeddings(self) -> int:
        query = (
            select(func.count())
            .select_from(
                s.embeddings.join(s.events, s.embeddings.c.event_key == s.events.c.event_key)
            )
            .where(
                s.events.c.deleted_at.is_(None),
                s.embeddings.c.embedding_status == int(EmbeddingStatus.PENDING),
            )
        )
        async with self._transaction() as connection:
            return int((await connection.execute(query)).scalar_one())

    async def event_scan_high_water(self) -> int:
        async with self._transaction() as connection:
            return int(
                (
                    await connection.execute(select(func.coalesce(func.max(s.events.c.id), 0)))
                ).scalar_one()
            )

    async def embedding_rebuild_page(
        self, *, after: int, through: int, limit: int
    ) -> list[tuple[int, MemoryEvent]]:
        async with self._transaction() as connection:
            rows = (
                await connection.execute(
                    select(s.events)
                    .where(
                        s.events.c.id > after,
                        s.events.c.id <= through,
                        s.events.c.deleted_at.is_(None),
                    )
                    .order_by(s.events.c.id)
                    .limit(limit)
                )
            ).mappings()
            return [(int(row["id"]), record(row).event) for row in rows]

    @staticmethod
    async def _embedding_sources(connection, event_ids: list[str]) -> dict[str, MemoryEvent]:
        sources = {}
        ids = list(dict.fromkeys(event_ids))
        for offset in range(0, len(ids), 500):
            page = ids[offset : offset + 500]
            rows = (
                await connection.execute(
                    select(s.events).where(
                        s.events.c.event_key.in_([identity(v) for v in page]),
                        s.events.c.event_id.in_(page),
                        s.events.c.deleted_at.is_(None),
                    )
                )
            ).mappings()
            sources.update({row["event_id"]: record(row).event for row in rows})
        return sources

    async def get_embedding_sources(self, event_ids: list[str]) -> list[MemoryEvent]:
        async with self._transaction() as connection:
            return list((await self._embedding_sources(connection, event_ids)).values())

    async def publish_event_embeddings(
        self, publications: list[EventEmbeddingPublication]
    ) -> set[str]:
        applied = set()
        async with self._transaction(write=True) as connection:
            sources = await self._embedding_sources(
                connection, [v.source.event_id for v in publications]
            )
            for item in publications:
                current = sources.get(item.source.event_id)
                if current is None or EventEmbeddingSource.from_event(current) != item.source:
                    continue
                if item.status == "ready" and (
                    item.profile is None
                    or item.profile_id != item.profile.profile_id
                    or not item.chunks
                ):
                    raise ValueError("Ready event embedding requires a matching profile and chunks")
                now = time.time()
                if item.profile is not None:
                    profile = item.profile
                    profile_key = identity(profile.profile_id)
                    exists = (
                        await connection.execute(
                            select(s.profiles.c.profile_key).where(
                                s.profiles.c.profile_key == profile_key
                            )
                        )
                    ).first()
                    if exists is None:
                        await connection.execute(
                            insert(s.profiles).values(
                                profile_key=profile_key,
                                profile_id=profile.profile_id,
                                provider_name=profile.provider_name,
                                model_name=profile.model_name,
                                embedding_dim=profile.dimension,
                                text_builder_version=profile.text_builder_version,
                                created_at=now,
                            )
                        )
                event_key = identity(item.source.event_id)
                if item.status == "ready":
                    await connection.execute(
                        delete(s.chunks).where(s.chunks.c.event_key == event_key)
                    )
                    for chunk in item.chunks:
                        chunk_id = f"{item.source.event_id}::chunk-{chunk.chunk_index}"
                        await connection.execute(
                            insert(s.chunks).values(
                                chunk_key=identity(chunk_id),
                                chunk_id=chunk_id,
                                event_key=event_key,
                                event_id=item.source.event_id,
                                chunk_index=chunk.chunk_index,
                                chunk_text=chunk.text,
                                char_start=chunk.char_start,
                                char_end=chunk.char_end,
                                token_estimate=chunk.token_estimate,
                                embedding_profile_id=item.profile_id,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                await connection.execute(
                    update(s.embeddings)
                    .where(s.embeddings.c.event_key == event_key)
                    .values(
                        embedding_status=embedding_status_code(item.status),
                        embedding_profile_id=item.profile_id,
                        embedding_chunk_count=len(item.chunks),
                        last_embedded_at=item.embedded_at,
                        updated_at=now,
                    )
                )
                applied.add(item.source.event_id)
        return applied

    async def remove_event_embedding_chunks(self, sources: list[EventEmbeddingSource]) -> list[str]:
        removed = []
        async with self._transaction(write=True) as connection:
            current = await self._embedding_sources(
                connection, [source.event_id for source in sources]
            )
            for source in sources:
                event = current.get(source.event_id)
                if event is None or EventEmbeddingSource.from_event(event) != source:
                    continue
                key = identity(source.event_id)
                removed.extend(
                    (
                        await connection.execute(
                            select(s.chunks.c.chunk_id).where(s.chunks.c.event_key == key)
                        )
                    ).scalars()
                )
                await connection.execute(delete(s.chunks).where(s.chunks.c.event_key == key))
                await connection.execute(
                    update(s.embeddings)
                    .where(s.embeddings.c.event_key == key)
                    .values(
                        embedding_status=int(EmbeddingStatus.SKIPPED),
                        embedding_profile_id=None,
                        embedding_chunk_count=0,
                        last_embedded_at=None,
                        updated_at=time.time(),
                    )
                )
        return removed

    async def fetch_embedding_chunks(self, chunk_ids: list[str]) -> list[EventChunkRecord]:
        records: list[EventChunkRecord] = []
        ids = list(dict.fromkeys(chunk_ids))
        columns = [s.chunks.c[name] for name in EventChunkRecord.__annotations__]
        async with self._transaction() as connection:
            for offset in range(0, len(ids), 500):
                page = ids[offset : offset + 500]
                query = (
                    select(*columns)
                    .select_from(
                        s.chunks.join(s.events, s.chunks.c.event_key == s.events.c.event_key)
                    )
                    .where(
                        s.chunks.c.chunk_key.in_([identity(v) for v in page]),
                        s.chunks.c.chunk_id.in_(page),
                        s.events.c.deleted_at.is_(None),
                    )
                )
                records.extend(
                    EventChunkRecord(**dict(row))
                    for row in (await connection.execute(query)).mappings()
                )
        return records

    async def visible_embedding_chunk_ids(self, chunk_ids: list[str]) -> set[str]:
        result = set()
        ids = list(dict.fromkeys(chunk_ids))
        async with self._transaction() as connection:
            for offset in range(0, len(ids), 500):
                page = ids[offset : offset + 500]
                query = (
                    select(s.chunks.c.chunk_id)
                    .select_from(
                        s.chunks.join(s.events, s.chunks.c.event_key == s.events.c.event_key)
                    )
                    .where(
                        s.chunks.c.chunk_key.in_([identity(v) for v in page]),
                        s.chunks.c.chunk_id.in_(page),
                        s.events.c.deleted_at.is_(None),
                        s.events.c.memory_domain.not_in(
                            [int(MemoryDomain.RUNTIME_TELEMETRY), int(MemoryDomain.SYSTEM_CONTROL)]
                        ),
                    )
                )
                result.update((await connection.execute(query)).scalars())
        return result
