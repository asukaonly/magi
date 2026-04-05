"""sqlite-vec backed indexing helpers for memory layers."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import asyncio
from dataclasses import dataclass
from typing import Any, Optional

import aiosqlite
import sqlite_vec

from ...core.sqlite import connect_aiosqlite
from .embedding_service import EmbeddingResult

logger = logging.getLogger(__name__)
_SAFE_IDENTIFIER = re.compile(r"[^a-z0-9_]+")


@dataclass(slots=True)
class VectorSearchHit:
    """One nearest-neighbor match from a sqlite-vec index."""

    entity_id: str
    distance: float


class SqliteVecIndex:
    """Manage sqlite-vec virtual tables and row-id mappings for one memory layer."""

    def __init__(
        self,
        *,
        db_path: str,
        registry_table: str,
        entity_column: str,
        vec_table_prefix: str,
    ) -> None:
        self._db_path = db_path
        self._registry_table = registry_table
        self._entity_column = entity_column
        self._vec_table_prefix = self._sanitize_identifier(vec_table_prefix)
        self._db: aiosqlite.Connection | None = None
        self._db_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._db = await connect_aiosqlite(self._db_path, profile="hot_write")
        await self._load_extension(self._db)
        async with self._db_lock:
            db = self._require_db()
            await self._ensure_registry_schema(db)
            await db.commit()
        self._initialized = True

    async def close(self) -> None:
        async with self._db_lock:
            if self._db is None:
                return
            await self._db.close()
            self._db = None
            self._initialized = False

    async def upsert(self, *, entity_id: str, embedding: EmbeddingResult, metadata: Optional[dict[str, Any]] = None) -> None:
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
        await self.initialize()
        async with self._db_lock:
            db = self._require_db()
            await self._ensure_registry_schema(db)
            vec_specs = {
                self._vec_table_name(item["embedding"].model_name, item["embedding"].dimension): item["embedding"].dimension
                for item in items
            }
            for vec_table, dimension in vec_specs.items():
                await self._ensure_vec_table(db, vec_table, dimension)

            now = await self._current_timestamp(db)
            for item in items:
                await self._upsert_one_locked(
                    db,
                    entity_id=str(item["entity_id"]),
                    embedding=item["embedding"],
                    metadata=item.get("metadata"),
                    now=now,
                )
            await db.commit()

    async def search(
        self,
        *,
        embedding: EmbeddingResult,
        limit: int,
        max_distance: float | None = None,
    ) -> list[VectorSearchHit]:
        await self.initialize()
        vec_table = self._vec_table_name(embedding.model_name, embedding.dimension)
        async with self._db_lock:
            db = self._require_db()
            await self._ensure_registry_schema(db)
            if not await self._table_exists(db, vec_table):
                return []

            if max_distance is not None:
                sql = f'SELECT rowid, distance FROM "{vec_table}" WHERE embedding MATCH ? AND distance < ? ORDER BY distance LIMIT ?'
                params = (sqlite_vec.serialize_float32(embedding.vector), float(max_distance), int(limit))
            else:
                sql = f'SELECT rowid, distance FROM "{vec_table}" WHERE embedding MATCH ? ORDER BY distance LIMIT ?'
                params = (sqlite_vec.serialize_float32(embedding.vector), int(limit))

            async with db.execute(sql, params) as cursor:
                vector_rows = await cursor.fetchall()

            if not vector_rows:
                return []

            rowids = [int(row["rowid"]) for row in vector_rows]
            placeholders = ", ".join("?" for _ in rowids)
            async with db.execute(
                f"SELECT vec_rowid, {self._entity_column} FROM {self._registry_table} WHERE vec_rowid IN ({placeholders})",
                tuple(rowids),
            ) as cursor:
                registry_rows = await cursor.fetchall()

        entity_by_rowid = {int(row["vec_rowid"]): str(row[self._entity_column]) for row in registry_rows}
        hits: list[VectorSearchHit] = []
        for row in vector_rows:
            entity_id = entity_by_rowid.get(int(row["rowid"]))
            if entity_id is None:
                continue
            hits.append(VectorSearchHit(entity_id=entity_id, distance=float(row["distance"])))
        return hits

    async def get_vectors(
        self,
        *,
        entity_ids: list[str],
    ) -> dict[str, list[float]]:
        """Return raw embedding vectors for the given *entity_ids*.

        Returns a mapping ``{entity_id: vector}`` for all IDs that have
        stored embeddings.  Missing IDs are silently omitted.
        """
        if not entity_ids:
            return {}
        await self.initialize()
        async with self._db_lock:
            db = self._require_db()
            await self._ensure_registry_schema(db)
            ph = ", ".join("?" for _ in entity_ids)
            async with db.execute(
                f"SELECT {self._entity_column}, vec_rowid, vec_table FROM {self._registry_table}"
                f" WHERE {self._entity_column} IN ({ph})",
                tuple(entity_ids),
            ) as cursor:
                registry_rows = await cursor.fetchall()

            if not registry_rows:
                return {}

            results: dict[str, list[float]] = {}
            # Group by vec_table for efficient batch reads
            table_groups: dict[str, list[tuple[str, int]]] = {}
            for row in registry_rows:
                table_name = str(row["vec_table"])
                eid = str(row[self._entity_column])
                rowid = int(row["vec_rowid"])
                table_groups.setdefault(table_name, []).append((eid, rowid))

            for table_name, entries in table_groups.items():
                if not await self._table_exists(db, table_name):
                    continue
                rowids = [r for _, r in entries]
                rid_ph = ", ".join("?" for _ in rowids)
                async with db.execute(
                    f'SELECT rowid, embedding FROM "{table_name}" WHERE rowid IN ({rid_ph})',
                    tuple(rowids),
                ) as cursor:
                    vec_rows = {int(r["rowid"]): r["embedding"] for r in await cursor.fetchall()}

                for eid, rowid in entries:
                    raw = vec_rows.get(rowid)
                    if raw is not None:
                        results[eid] = sqlite_vec.deserialize_float32(raw)
        return results

    async def delete_entity(self, *, entity_id: str) -> None:
        await self.initialize()
        async with self._db_lock:
            db = self._require_db()
            await self._ensure_registry_schema(db)
            async with db.execute(
                f"SELECT vec_rowid, vec_table FROM {self._registry_table} WHERE {self._entity_column} = ?",
                (entity_id,),
            ) as cursor:
                rows = await cursor.fetchall()
            for row in rows:
                await db.execute(f'DELETE FROM "{row["vec_table"]}" WHERE rowid = ?', (int(row["vec_rowid"]),))
            await db.execute(
                f"DELETE FROM {self._registry_table} WHERE {self._entity_column} = ?",
                (entity_id,),
            )
            await db.commit()

    async def clear(self) -> None:
        await self.initialize()
        async with self._db_lock:
            db = self._require_db()
            await self._ensure_registry_schema(db)
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE ? AND name != ?",
                (f"{self._vec_table_prefix}%", self._registry_table),
            ) as cursor:
                vec_tables = [str(row[0]) for row in await cursor.fetchall()]
            for table_name in vec_tables:
                await db.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            await db.execute(f"DELETE FROM {self._registry_table}")
            await db.commit()

    async def _ensure_registry_schema(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._registry_table} (
                vec_rowid INTEGER PRIMARY KEY,
                {self._entity_column} TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                vec_table TEXT NOT NULL,
                metadata TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE({self._entity_column}, embedding_model)
            )
            """
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._registry_table}_{self._entity_column} ON {self._registry_table}({self._entity_column})"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._registry_table}_model ON {self._registry_table}(embedding_model)"
        )

    async def _ensure_vec_table(self, db: aiosqlite.Connection, table_name: str, dimension: int) -> None:
        if await self._table_exists(db, table_name):
            return
        await db.execute(
            f'CREATE VIRTUAL TABLE "{table_name}" USING vec0(embedding float[{int(dimension)}])'
        )

    async def _load_extension(self, db: aiosqlite.Connection) -> None:
        if getattr(db, "_sqlite_vec_loaded", False):
            return
        if not hasattr(db, "enable_load_extension"):
            raise RuntimeError("SQLite loadable extensions are not enabled in this Python runtime")
        await db.enable_load_extension(True)
        try:
            await db.execute("SELECT load_extension(?)", (sqlite_vec.loadable_path(),))
        finally:
            await db.enable_load_extension(False)
        setattr(db, "_sqlite_vec_loaded", True)

    async def _table_exists(self, db: aiosqlite.Connection, table_name: str) -> bool:
        async with db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None

    async def _current_timestamp(self, db: aiosqlite.Connection) -> float:
        async with db.execute("SELECT unixepoch('subsec')") as cursor:
            row = await cursor.fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    def _vec_table_name(self, embedding_model: str, dimension: int) -> str:
        token = hashlib.sha1(f"{embedding_model}:{dimension}".encode("utf-8")).hexdigest()[:12]
        return f"{self._vec_table_prefix}_{token}"

    def _sanitize_identifier(self, value: str) -> str:
        return _SAFE_IDENTIFIER.sub("_", value.lower()).strip("_")

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SqliteVecIndex is not initialized")
        return self._db

    async def _upsert_one_locked(
        self,
        db: aiosqlite.Connection,
        *,
        entity_id: str,
        embedding: EmbeddingResult,
        metadata: Optional[dict[str, Any]],
        now: float,
    ) -> None:
        vec_table = self._vec_table_name(embedding.model_name, embedding.dimension)
        async with db.execute(
            f"SELECT vec_rowid, vec_table, created_at FROM {self._registry_table} WHERE {self._entity_column} = ? AND embedding_model = ?",
            (entity_id, embedding.model_name),
        ) as cursor:
            existing = await cursor.fetchone()

        if existing is None:
            insert_cursor = await db.execute(
                f"""
                INSERT INTO {self._registry_table}(
                    {self._entity_column}, embedding_model, embedding_dim, vec_table,
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
                UPDATE {self._registry_table}
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
        await db.execute(
            f'INSERT INTO "{vec_table}"(rowid, embedding) VALUES (?, ?)',
            (vec_rowid, sqlite_vec.serialize_float32(embedding.vector)),
        )
