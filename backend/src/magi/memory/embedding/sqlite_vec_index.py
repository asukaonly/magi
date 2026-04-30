"""sqlite-vec backed indexing helpers for memory layers."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re

import aiosqlite
import sqlite_vec

from ...core.sqlite import connect_aiosqlite
from .sqlite_vec_search import SqliteVecSearchMixin
from .sqlite_vec_types import VectorSearchHit, _deserialize_float32_blob
from .sqlite_vec_writes import SqliteVecWriteMixin

logger = logging.getLogger(__name__)
_SAFE_IDENTIFIER = re.compile(r"[^a-z0-9_]+")


class SqliteVecIndex(SqliteVecWriteMixin, SqliteVecSearchMixin):
    """Manage sqlite-vec virtual tables and row-id mappings for one memory layer."""

    def __init__(
        self,
        *,
        db_path: str,
        registry_table: str,
        entity_column: str,
        vec_table_prefix: str,
        partition_key_column: str | None = None,
    ) -> None:
        self._db_path = db_path
        self._registry_table = registry_table
        self._entity_column = entity_column
        self._vec_table_prefix = self._sanitize_identifier(vec_table_prefix)
        self._partition_key_column = partition_key_column
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

    async def _ensure_vec_table(
        self, db: aiosqlite.Connection, table_name: str, dimension: int
    ) -> None:
        if await self._table_exists(db, table_name):
            return
        pk_clause = f", {self._partition_key_column} text partition key" if self._partition_key_column else ""
        await db.execute(
            f'CREATE VIRTUAL TABLE "{table_name}" USING vec0(embedding float[{int(dimension)}]{pk_clause})'
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


__all__ = ["SqliteVecIndex", "VectorSearchHit", "_deserialize_float32_blob", "sqlite_vec"]
