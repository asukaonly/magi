"""Write and maintenance helpers for sqlite-vec backed memory indexes."""

from __future__ import annotations

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
        async with host._db_lock:
            db = host._require_db()
            await host._ensure_registry_schema(db)
            vec_specs = {
                host._vec_table_name(item["embedding"].model_name, item["embedding"].dimension): item[
                    "embedding"
                ].dimension
                for item in items
            }
            for vec_table, dimension in vec_specs.items():
                await host._ensure_vec_table(db, vec_table, dimension)

            now = await host._current_timestamp(db)
            for item in items:
                await self._upsert_one_locked(
                    db,
                    entity_id=str(item["entity_id"]),
                    embedding=item["embedding"],
                    metadata=item.get("metadata"),
                    now=now,
                )
            await db.commit()

    async def delete_entity(self, *, entity_id: str) -> None:
        host = cast(Any, self)
        await host.initialize()
        async with host._db_lock:
            db = host._require_db()
            await host._ensure_registry_schema(db)
            async with db.execute(
                f"SELECT vec_rowid, vec_table FROM {host._registry_table} WHERE {host._entity_column} = ?",
                (entity_id,),
            ) as cursor:
                rows = await cursor.fetchall()
            for row in rows:
                await db.execute(f'DELETE FROM "{row["vec_table"]}" WHERE rowid = ?', (int(row["vec_rowid"]),))
            await db.execute(
                f"DELETE FROM {host._registry_table} WHERE {host._entity_column} = ?",
                (entity_id,),
            )
            await db.commit()

    async def clear(self) -> None:
        host = cast(Any, self)
        await host.initialize()
        async with host._db_lock:
            db = host._require_db()
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
                await db.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            await db.execute(f"DELETE FROM {host._registry_table}")
            await db.commit()

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
        vec_table = host._vec_table_name(embedding.model_name, embedding.dimension)
        async with db.execute(
            f"SELECT vec_rowid, vec_table, created_at FROM {host._registry_table} WHERE {host._entity_column} = ? AND embedding_model = ?",
            (entity_id, embedding.model_name),
        ) as cursor:
            existing = await cursor.fetchone()

        if existing is None:
            insert_cursor = await db.execute(
                f"""
                INSERT INTO {host._registry_table}(
                    {host._entity_column}, embedding_model, embedding_dim, vec_table,
                    metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id,
                    embedding.model_name,
                    int(embedding.dimension),
                    vec_table,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            vec_rowid = int(insert_cursor.lastrowid)
            previous_table = None
        else:
            vec_rowid = int(existing["vec_rowid"])
            previous_table = str(existing["vec_table"])
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
