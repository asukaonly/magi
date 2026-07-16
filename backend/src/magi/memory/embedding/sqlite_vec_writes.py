"""Write and maintenance helpers for sqlite-vec backed memory indexes."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import json
from typing import Any, Optional, cast

import aiosqlite
import sqlite_vec

from .embedding_service import EmbeddingResult


class SqliteVecWriteMixin:
    """Upsert, delete, and clear operations for sqlite-vec indexes."""

    async def upsert(
        self,
        *,
        entity_id: str,
        embedding: EmbeddingResult,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        await self.upsert_many(
            [
                {
                    "entity_id": entity_id,
                    "embedding": embedding,
                    "metadata": metadata,
                }
            ]
        )

    async def upsert_many(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        host = cast(Any, self)
        await host.initialize()
        async with host._coordinator.write_lock:
            async with host._db_lock:
                db = host._require_db()
                rebuild_session = host._active_rebuild_session()
                entity_ids = {str(item["entity_id"]) for item in items}
                if rebuild_session is None:
                    # Fence first: cancellation can make commit outcome unknowable.
                    host._record_normal_writes(entity_ids)
                else:
                    host._validate_rebuild_identity(
                        rebuild_session,
                        {
                            (
                                host._embedding_model_key(item["embedding"]),
                                int(item["embedding"].dimension),
                            )
                            for item in items
                        },
                    )
                writable_items = [
                    item
                    for item in items
                    if rebuild_session is None
                    or host._rebuild_write_is_current(
                        rebuild_session,
                        str(item["entity_id"]),
                    )
                ]
                if not writable_items:
                    return
                vec_specs = {
                    host._vec_table_name(
                        host._embedding_model_key(item["embedding"]),
                        item["embedding"].dimension,
                    ): item["embedding"].dimension
                    for item in writable_items
                }
                try:
                    await host._ensure_registry_schema(db)
                    if rebuild_session is not None:
                        await host._prepare_rebuild_cleanup_tracking(db, rebuild_session)
                    for vec_table, dimension in vec_specs.items():
                        await host._ensure_vec_table(db, vec_table, dimension)

                    now = await host._current_timestamp(db)
                    for item in writable_items:
                        await self._upsert_one_locked(
                            db,
                            entity_id=str(item["entity_id"]),
                            embedding=item["embedding"],
                            metadata=item.get("metadata"),
                            now=now,
                        )
                        if rebuild_session is not None and rebuild_session.cleanup_needed:
                            await db.execute(
                                f"INSERT OR IGNORE INTO {host._rebuild_marks_table}(entity_id) VALUES (?)",
                                (str(item["entity_id"]),),
                            )
                    await db.commit()
                except BaseException:
                    await asyncio.shield(db.rollback())
                    raise

    async def delete_entity(self, *, entity_id: str) -> None:
        host = cast(Any, self)
        await host.initialize()
        async with host._coordinator.write_lock:
            async with host._db_lock:
                db = host._require_db()
                rebuild_session = host._active_rebuild_session()
                if rebuild_session is None:
                    host._record_normal_writes({entity_id})
                elif not host._rebuild_write_is_current(rebuild_session, entity_id):
                    return
                try:
                    await host._ensure_registry_schema(db)
                    async with db.execute(
                        f"SELECT vec_rowid, vec_table FROM {host._registry_table} WHERE {host._entity_column} = ?",
                        (entity_id,),
                    ) as cursor:
                        rows = await cursor.fetchall()
                    for row in rows:
                        await db.execute(
                            f'DELETE FROM "{row["vec_table"]}" WHERE rowid = ?',
                            (int(row["vec_rowid"]),),
                        )
                    await db.execute(
                        f"DELETE FROM {host._registry_table} WHERE {host._entity_column} = ?",
                        (entity_id,),
                    )
                    await db.commit()
                except BaseException:
                    await asyncio.shield(db.rollback())
                    raise

    async def delete_embedding(
        self,
        *,
        entity_id: str,
        embedding: EmbeddingResult,
    ) -> None:
        """Delete one entity vector identity without removing recovery copies."""

        host = cast(Any, self)
        await host.initialize()
        async with host._coordinator.write_lock:
            async with host._db_lock:
                db = host._require_db()
                rebuild_session = host._active_rebuild_session()
                if rebuild_session is None:
                    host._record_normal_writes({entity_id})
                elif not host._rebuild_write_is_current(rebuild_session, entity_id):
                    return
                model_key = host._embedding_model_key(embedding)
                try:
                    await host._ensure_registry_schema(db)
                    async with db.execute(
                        f"""
                        SELECT vec_rowid, vec_table
                        FROM {host._registry_table}
                        WHERE {host._entity_column} = ? AND embedding_model = ?
                        """,
                        (entity_id, model_key),
                    ) as cursor:
                        row = await cursor.fetchone()
                    if row is not None:
                        await db.execute(
                            f'DELETE FROM "{row["vec_table"]}" WHERE rowid = ?',
                            (int(row["vec_rowid"]),),
                        )
                        await db.execute(
                            f"DELETE FROM {host._registry_table} WHERE vec_rowid = ?",
                            (int(row["vec_rowid"]),),
                        )
                    if (
                        rebuild_session is not None
                        and model_key == rebuild_session.target_model_key
                    ):
                        await db.execute(
                            f"DELETE FROM {host._rebuild_marks_table} WHERE entity_id = ?",
                            (entity_id,),
                        )
                    await db.commit()
                except BaseException:
                    await asyncio.shield(db.rollback())
                    raise

    async def clear(self) -> None:
        host = cast(Any, self)
        await host.initialize()
        async with host._coordinator.write_lock:
            async with host._db_lock:
                db = host._require_db()
                host._record_clear()
                try:
                    await host._ensure_registry_schema(db)
                    async with db.execute(
                        "SELECT name FROM sqlite_master"
                        " WHERE type = 'table'"
                        " AND name LIKE ?"
                        " AND name != ?"
                        " AND sql LIKE 'CREATE VIRTUAL TABLE%'",
                        (f"{host._vec_table_prefix}%", host._registry_table),
                    ) as cursor:
                        vec_tables = [str(row[0]) for row in await cursor.fetchall()]
                    for table_name in vec_tables:
                        await db.execute(f'DELETE FROM "{table_name}"')
                    await db.execute(f"DELETE FROM {host._registry_table}")
                    await db.commit()
                except BaseException:
                    await asyncio.shield(db.rollback())
                    raise

    async def prune_orphans(
        self,
        *,
        valid_entity_query: str,
        parameters: tuple[Any, ...] = (),
        batch_size: int = 250,
        mutation_guard_factory: Any | None = None,
    ) -> int:
        """Delete vectors whose source entity is absent from an internal query."""

        host = cast(Any, self)
        await host.initialize()
        normalized_batch_size = max(1, int(batch_size))
        pruned = 0
        while True:
            async with AsyncExitStack() as stack:
                if mutation_guard_factory is not None:
                    await stack.enter_async_context(mutation_guard_factory())
                await stack.enter_async_context(host._coordinator.write_lock)
                await stack.enter_async_context(host._db_lock)
                db = host._require_db()
                try:
                    await db.execute("BEGIN IMMEDIATE")
                    async with db.execute(
                        f"""
                        SELECT registry.vec_rowid, registry.vec_table
                        FROM {host._registry_table} AS registry
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM ({valid_entity_query}) AS valid
                            WHERE valid.entity_id = registry.{host._entity_column}
                        )
                        LIMIT ?
                        """,
                        (*parameters, normalized_batch_size),
                    ) as cursor:
                        rows = await cursor.fetchall()
                    if not rows:
                        await db.commit()
                        return pruned
                    for row in rows:
                        vec_table = str(row["vec_table"])
                        vec_rowid = int(row["vec_rowid"])
                        if await host._table_exists(db, vec_table):
                            await db.execute(
                                f'DELETE FROM "{vec_table}" WHERE rowid = ?',
                                (vec_rowid,),
                            )
                        await db.execute(
                            f"DELETE FROM {host._registry_table} WHERE vec_rowid = ?",
                            (vec_rowid,),
                        )
                    await db.commit()
                    pruned += len(rows)
                except BaseException:
                    await asyncio.shield(db.rollback())
                    raise
            await asyncio.sleep(0)

    async def _finalize_rebuild_session(self, session: Any) -> None:
        """Retire stale model copies for entities refreshed by a successful rebuild."""

        host = cast(Any, self)
        host._assert_rebuild_identity_stable(session)
        if not session.cleanup_needed or session.target_model_key is None:
            return
        while True:
            async with host._coordinator.write_lock:
                async with host._db_lock:
                    if host._coordinator.clear_epoch != session.baseline_clear_epoch:
                        return
                    db = host._require_db()
                    try:
                        async with db.execute(
                            f"SELECT entity_id FROM {host._rebuild_marks_table} LIMIT 250"
                        ) as cursor:
                            rows = await cursor.fetchall()
                        if not rows:
                            return
                        for row in rows:
                            entity_id = str(row["entity_id"])
                            if host._rebuild_write_is_current(session, entity_id):
                                await self._delete_obsolete_models_locked(
                                    db,
                                    entity_id=entity_id,
                                    retained_models={session.target_model_key},
                                )
                            await db.execute(
                                f"DELETE FROM {host._rebuild_marks_table} WHERE entity_id = ?",
                                (entity_id,),
                            )
                        await db.commit()
                    except BaseException:
                        await asyncio.shield(db.rollback())
                        raise
            await asyncio.sleep(0)

    async def _delete_obsolete_models_locked(
        self,
        db: aiosqlite.Connection,
        *,
        entity_id: str,
        retained_models: set[str],
    ) -> None:
        host = cast(Any, self)
        async with db.execute(
            f"""
            SELECT vec_rowid, vec_table, embedding_model
            FROM {host._registry_table}
            WHERE {host._entity_column} = ?
            """,
            (entity_id,),
        ) as cursor:
            rows = await cursor.fetchall()

        obsolete_rows = [row for row in rows if str(row["embedding_model"]) not in retained_models]
        for row in obsolete_rows:
            vec_table = str(row["vec_table"])
            vec_rowid = int(row["vec_rowid"])
            if await host._table_exists(db, vec_table):
                await db.execute(f'DELETE FROM "{vec_table}" WHERE rowid = ?', (vec_rowid,))
            await db.execute(
                f"DELETE FROM {host._registry_table} WHERE vec_rowid = ?",
                (vec_rowid,),
            )

    async def _upsert_one_locked(
        self,
        db: aiosqlite.Connection,
        *,
        entity_id: str,
        embedding: EmbeddingResult,
        metadata: Optional[dict[str, Any]],
        now: float,
    ) -> None:
        host = cast(Any, self)
        embedding_model_key = host._embedding_model_key(embedding)
        vec_table = host._vec_table_name(embedding_model_key, embedding.dimension)
        existing = await self._fetch_registry_row(
            db,
            entity_id=entity_id,
            embedding_model_key=embedding_model_key,
        )

        if existing is None:
            vec_rowid = await self._insert_registry_row(
                db,
                entity_id=entity_id,
                embedding_model_key=embedding_model_key,
                embedding=embedding,
                vec_table=vec_table,
                metadata=metadata,
                now=now,
            )
            previous_table = None
        else:
            vec_rowid = int(existing["vec_rowid"])
            previous_table = str(existing["vec_table"])
            await self._update_registry_row(
                db,
                vec_rowid=vec_rowid,
                embedding=embedding,
                vec_table=vec_table,
                metadata=metadata,
                now=now,
            )

        await self._replace_vector_row(
            db,
            vec_rowid=vec_rowid,
            vec_table=vec_table,
            previous_table=previous_table,
            embedding=embedding,
            metadata=metadata,
        )

    async def _fetch_registry_row(
        self,
        db: aiosqlite.Connection,
        *,
        entity_id: str,
        embedding_model_key: str,
    ) -> aiosqlite.Row | None:
        host = cast(Any, self)
        async with db.execute(
            f"""
            SELECT vec_rowid, vec_table, created_at
            FROM {host._registry_table}
            WHERE {host._entity_column} = ? AND embedding_model = ?
            """,
            (entity_id, embedding_model_key),
        ) as cursor:
            return await cursor.fetchone()

    async def _insert_registry_row(
        self,
        db: aiosqlite.Connection,
        *,
        entity_id: str,
        embedding_model_key: str,
        embedding: EmbeddingResult,
        vec_table: str,
        metadata: Optional[dict[str, Any]],
        now: float,
    ) -> int:
        host = cast(Any, self)
        insert_cursor = await db.execute(
            f"""
            INSERT INTO {host._registry_table}(
                {host._entity_column}, embedding_model, embedding_dim, vec_table,
                metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                embedding_model_key,
                int(embedding.dimension),
                vec_table,
                json.dumps(metadata or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        return int(insert_cursor.lastrowid)

    async def _update_registry_row(
        self,
        db: aiosqlite.Connection,
        *,
        vec_rowid: int,
        embedding: EmbeddingResult,
        vec_table: str,
        metadata: Optional[dict[str, Any]],
        now: float,
    ) -> None:
        host = cast(Any, self)
        await db.execute(
            f"""
            UPDATE {host._registry_table}
            SET embedding_dim = ?, vec_table = ?, metadata = ?, updated_at = ?
            WHERE vec_rowid = ?
            """,
            (
                int(embedding.dimension),
                vec_table,
                json.dumps(metadata or {}, ensure_ascii=False),
                now,
                vec_rowid,
            ),
        )

    async def _replace_vector_row(
        self,
        db: aiosqlite.Connection,
        *,
        vec_rowid: int,
        vec_table: str,
        previous_table: str | None,
        embedding: EmbeddingResult,
        metadata: Optional[dict[str, Any]],
    ) -> None:
        host = cast(Any, self)
        if previous_table:
            await db.execute(f'DELETE FROM "{previous_table}" WHERE rowid = ?', (vec_rowid,))
        await db.execute(f'DELETE FROM "{vec_table}" WHERE rowid = ?', (vec_rowid,))

        pk_col = host._partition_key_column
        partition_value = (metadata or {}).get("partition_value") if pk_col else None
        if pk_col and partition_value is not None:
            await db.execute(
                f'INSERT INTO "{vec_table}"(rowid, embedding, {pk_col}) VALUES (?, ?, ?)',
                (vec_rowid, sqlite_vec.serialize_float32(embedding.vector), partition_value),
            )
        else:
            await db.execute(
                f'INSERT INTO "{vec_table}"(rowid, embedding) VALUES (?, ?)',
                (vec_rowid, sqlite_vec.serialize_float32(embedding.vector)),
            )


__all__ = ["SqliteVecWriteMixin"]
