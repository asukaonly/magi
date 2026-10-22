"""SQLite ownership of event embedding publication and source visibility."""

from __future__ import annotations

import time

import aiosqlite

from .connection import event_connection
from ...event_contracts import MemoryDomain, MemoryEvent
from ..embedding_contracts import EventChunkRecord, EventEmbeddingPublication, EventEmbeddingSource
from ..embeddings.common import EmbeddingStatus, embedding_status_code
from .event_mapping import event_record_from_mapping


class SqliteEventEmbeddingState:
    _db_path: str

    async def count_pending_embeddings(self) -> int:
        async with event_connection(self._db_path, profile="readonly") as db:
            async with db.execute(
                "SELECT COUNT(*) FROM l1_event_embedding_state AS state "
                "JOIN fact_events AS event USING(event_id) "
                "WHERE state.embedding_status=? AND event.deleted_at IS NULL",
                (int(EmbeddingStatus.PENDING),),
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0])

    async def event_scan_high_water(self) -> int:
        async with event_connection(self._db_path, profile="readonly") as db:
            async with db.execute("SELECT COALESCE(MAX(id), 0) FROM fact_events") as cursor:
                row = await cursor.fetchone()
        return int(row[0])

    async def embedding_rebuild_page(
        self, *, after: int, through: int, limit: int,
    ) -> list[tuple[int, MemoryEvent]]:
        async with event_connection(self._db_path, profile="readonly") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM fact_events WHERE id > ? AND id <= ? "
                "AND deleted_at IS NULL ORDER BY id LIMIT ?", (after, through, limit),
            ) as cursor:
                return [
                    (int(row["id"]), event_record_from_mapping(dict(row)).event)
                    for row in await cursor.fetchall()
                ]

    async def get_embedding_sources(self, event_ids: list[str]) -> list[MemoryEvent]:
        async with event_connection(self._db_path, profile="readonly") as db:
            return list((await self._load_embedding_sources(db, event_ids)).values())

    @staticmethod
    async def _load_embedding_sources(
        db: aiosqlite.Connection, event_ids: list[str],
    ) -> dict[str, MemoryEvent]:
        db.row_factory = aiosqlite.Row
        sources: dict[str, MemoryEvent] = {}
        ids = list(dict.fromkeys(event_ids))
        for offset in range(0, len(ids), 500):
            batch = ids[offset:offset + 500]
            placeholders = ",".join("?" for _ in batch)
            async with db.execute(
                f"SELECT * FROM fact_events WHERE event_id IN ({placeholders}) AND deleted_at IS NULL",
                tuple(batch),
            ) as cursor:
                for row in await cursor.fetchall():
                    event = event_record_from_mapping(dict(row)).event
                    sources[event.event_id] = event
        return sources

    async def publish_event_embeddings(self, publications: list[EventEmbeddingPublication]) -> set[str]:
        """Commit source-checked chunks, profiles and status as one write unit."""
        if not publications:
            return set()
        applied: set[str] = set()
        now = time.time()
        async with event_connection(self._db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            sources = await self._load_embedding_sources(db, [item.source.event_id for item in publications])
            for item in publications:
                current = sources.get(item.source.event_id)
                if current is None or EventEmbeddingSource.from_event(current) != item.source:
                    continue
                if item.status == "ready":
                    if item.profile is None or item.profile_id != item.profile.profile_id or not item.chunks:
                        raise ValueError("Ready event embedding requires a matching profile and chunks")
                if item.profile is not None:
                    profile = item.profile
                    await db.execute(
                        "INSERT OR IGNORE INTO embedding_profiles "
                        "(profile_id, provider_name, model_name, embedding_dim, text_builder_version, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (profile.profile_id, profile.provider_name, profile.model_name,
                         profile.dimension, profile.text_builder_version, now),
                    )
                if item.status == "ready":
                    await db.execute("DELETE FROM l1_event_chunks WHERE event_id = ?", (item.source.event_id,))
                    await db.executemany(
                        "INSERT INTO l1_event_chunks "
                        "(chunk_id, event_id, chunk_index, chunk_text, char_start, char_end, "
                        "token_estimate, embedding_profile_id, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            (f"{item.source.event_id}::chunk-{chunk.chunk_index}", item.source.event_id,
                             chunk.chunk_index, chunk.text, chunk.char_start, chunk.char_end,
                             chunk.token_estimate, item.profile_id, now, now)
                            for chunk in item.chunks
                        ],
                    )
                await db.execute(
                    "UPDATE l1_event_embedding_state SET embedding_status=?, embedding_profile_id=?, "
                    "embedding_chunk_count=?, last_embedded_at=?, updated_at=? WHERE event_id=?",
                    (embedding_status_code(item.status), item.profile_id, len(item.chunks),
                     item.embedded_at, now, item.source.event_id),
                )
                applied.add(item.source.event_id)
            await db.commit()
        return applied

    async def remove_event_embedding_chunks(self, sources: list[EventEmbeddingSource]) -> list[str]:
        """Detach unembeddable source chunks only while their snapshots still match."""
        detached: list[str] = []
        async with event_connection(self._db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            current = await self._load_embedding_sources(db, [source.event_id for source in sources])
            for source in sources:
                event = current.get(source.event_id)
                if event is None or EventEmbeddingSource.from_event(event) != source:
                    continue
                async with db.execute(
                    "SELECT chunk_id FROM l1_event_chunks WHERE event_id = ?", (source.event_id,),
                ) as cursor:
                    detached.extend(str(row[0]) for row in await cursor.fetchall())
                await db.execute("DELETE FROM l1_event_chunks WHERE event_id = ?", (source.event_id,))
                await db.execute(
                    "UPDATE l1_event_embedding_state SET embedding_status=?, embedding_profile_id=NULL, "
                    "embedding_chunk_count=0, last_embedded_at=NULL, updated_at=? WHERE event_id=?",
                    (int(EmbeddingStatus.SKIPPED), time.time(), source.event_id),
                )
            await db.commit()
        return detached

    async def fetch_embedding_chunks(self, chunk_ids: list[str]) -> list[EventChunkRecord]:
        records: list[EventChunkRecord] = []
        ids = list(dict.fromkeys(chunk_ids))
        async with event_connection(self._db_path, profile="readonly") as db:
            for offset in range(0, len(ids), 500):
                batch = ids[offset:offset + 500]
                placeholders = ",".join("?" for _ in batch)
                async with db.execute(
                    "SELECT chunks.chunk_id, chunks.event_id, chunks.chunk_index, chunks.chunk_text, "
                    "chunks.char_start, chunks.char_end FROM l1_event_chunks chunks "
                    "JOIN fact_events events USING(event_id) "
                    f"WHERE chunk_id IN ({placeholders}) AND events.deleted_at IS NULL", tuple(batch),
                ) as cursor:
                    records.extend(EventChunkRecord(
                        chunk_id=str(row[0]), event_id=str(row[1]), chunk_index=int(row[2]),
                        chunk_text=str(row[3]), char_start=int(row[4]), char_end=int(row[5]),
                    ) for row in await cursor.fetchall())
        return records

    async def visible_embedding_chunk_ids(self, chunk_ids: list[str]) -> set[str]:
        visible: set[str] = set()
        ids = list(dict.fromkeys(chunk_ids))
        async with event_connection(self._db_path, profile="readonly") as db:
            for offset in range(0, len(ids), 500):
                batch = ids[offset:offset + 500]
                placeholders = ",".join("?" for _ in batch)
                async with db.execute(
                    "SELECT chunk_id FROM l1_event_chunks JOIN fact_events USING(event_id) "
                    f"WHERE chunk_id IN ({placeholders}) AND deleted_at IS NULL "
                    "AND memory_domain NOT IN (?, ?)",
                    (*batch, int(MemoryDomain.RUNTIME_TELEMETRY), int(MemoryDomain.SYSTEM_CONTROL)),
                ) as cursor:
                    visible.update(str(row[0]) for row in await cursor.fetchall())
        return visible
