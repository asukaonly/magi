"""Chunk row persistence helpers for L1 event embeddings."""

from __future__ import annotations

import time
from typing import Any, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.chunking import ChunkedText, chunk_sentences
from ...embedding.embedding_service import EmbeddingProfile
from ...event_contracts import MemoryEvent
from .common import EVENT_CHUNKS_TABLE, L1EventEmbeddingHostProtocol


class L1EventEmbeddingChunkMixin:
    """Own L1 event embedding chunk construction and storage."""

    def _build_event_embedding_chunks(self, event: MemoryEvent) -> list[ChunkedText]:
        host = cast(L1EventEmbeddingHostProtocol, self)
        return cast(list[ChunkedText], chunk_sentences(host.get_embedding_text(event)))

    def _chunk_id_for_event(self, event_id: str, chunk_index: int) -> str:
        return f"{event_id}::chunk-{chunk_index}"

    async def _replace_event_chunks(
        self,
        entries: list[tuple[MemoryEvent, list[ChunkedText], list[Any], EmbeddingProfile]],
    ) -> None:
        if not entries:
            return
        host = cast(L1EventEmbeddingHostProtocol, self)
        now = time.time()
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            for event, chunks, _, profile in entries:
                await db.execute(
                    f"DELETE FROM {EVENT_CHUNKS_TABLE} WHERE event_id = ?",
                    (event.event_id,),
                )
                await db.executemany(
                    f"""
                    INSERT INTO {EVENT_CHUNKS_TABLE}(
                        chunk_id, event_id, chunk_index, chunk_text, char_start, char_end,
                        token_estimate, embedding_profile_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            self._chunk_id_for_event(event.event_id, chunk.chunk_index),
                            event.event_id,
                            chunk.chunk_index,
                            chunk.text,
                            chunk.char_start,
                            chunk.char_end,
                            chunk.token_estimate,
                            profile.profile_id,
                            now,
                            now,
                        )
                        for chunk in chunks
                    ],
                )
            await db.commit()

    async def _fetch_chunk_rows_by_ids(self, chunk_ids: list[str]) -> list[aiosqlite.Row]:
        if not chunk_ids:
            return []
        host = cast(L1EventEmbeddingHostProtocol, self)
        placeholders = ", ".join("?" for _ in chunk_ids)
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT chunk_id, event_id, chunk_index, chunk_text, char_start, char_end
                FROM {EVENT_CHUNKS_TABLE}
                WHERE chunk_id IN ({placeholders})
                """,
                tuple(chunk_ids),
            ) as cursor:
                return cast(list[aiosqlite.Row], await cursor.fetchall())

    async def _list_chunk_ids_for_event(self, event_id: str) -> list[str]:
        host = cast(L1EventEmbeddingHostProtocol, self)
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            async with db.execute(
                f"SELECT chunk_id FROM {EVENT_CHUNKS_TABLE} WHERE event_id = ?",
                (event_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]
