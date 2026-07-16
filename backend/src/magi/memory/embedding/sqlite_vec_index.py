"""sqlite-vec backed indexing helpers for memory layers."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import logging
from pathlib import Path
import re
import sys
from typing import AsyncIterator
from weakref import WeakValueDictionary

import aiosqlite
import sqlite_vec

from ...core.sqlite import connect_aiosqlite
from .sqlite_vec_search import SqliteVecSearchMixin
from .sqlite_vec_types import VectorSearchHit, _deserialize_float32_blob
from .sqlite_vec_writes import SqliteVecWriteMixin

logger = logging.getLogger(__name__)
_SAFE_IDENTIFIER = re.compile(r"[^a-z0-9_]+")


class EmbeddingRebuildIdentityChangedError(RuntimeError):
    """Raised when one rebuild produces incompatible vector identities."""


@dataclass(slots=True)
class _RebuildSession:
    """Process-local coordination state for one exclusive vector rebuild."""

    baseline_write_epoch: int
    baseline_clear_epoch: int
    target_model_key: str | None = None
    target_dimension: int | None = None
    cleanup_needed: bool | None = None
    identity_changed: bool = False
    active: bool = True


@dataclass
class _VectorIndexCoordinator:
    """Share rebuild ordering across instances for one logical vector index."""

    rebuild_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    source_write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    write_epoch: int = 0
    clear_epoch: int = 0
    entity_write_epochs: dict[str, int] = field(default_factory=dict)
    current_rebuild_session: _RebuildSession | None = None


_INDEX_COORDINATORS: WeakValueDictionary[tuple[str, str], _VectorIndexCoordinator] = (
    WeakValueDictionary()
)


def _coordinator_for(db_path: str, registry_table: str) -> _VectorIndexCoordinator:
    key = (str(Path(db_path).expanduser().resolve()), registry_table)
    coordinator = _INDEX_COORDINATORS.get(key)
    if coordinator is None:
        coordinator = _VectorIndexCoordinator()
        _INDEX_COORDINATORS[key] = coordinator
    return coordinator


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
        self._rebuild_marks_table = self._sanitize_identifier(f"{registry_table}_rebuild_marks")
        self._partition_key_column = partition_key_column
        self._db: aiosqlite.Connection | None = None
        self._db_lock = asyncio.Lock()
        self._initialized = False
        self._coordinator = _coordinator_for(db_path, registry_table)
        self._rebuild_lock = self._coordinator.rebuild_lock
        self._rebuild_context: ContextVar[_RebuildSession | None] = ContextVar(
            f"sqlite_vec_rebuild_{id(self)}",
            default=None,
        )
        self._entity_write_epochs = self._coordinator.entity_write_epochs

    async def initialize(self) -> None:
        async with self._db_lock:
            if self._initialized:
                return
            db = await connect_aiosqlite(self._db_path, profile="hot_write")
            try:
                await self._load_extension(db)
                await self._ensure_registry_schema(db)
                await db.commit()
            except BaseException:
                await asyncio.shield(db.close())
                raise
            self._db = db
            self._initialized = True

    @asynccontextmanager
    async def rebuild_session(self) -> AsyncIterator[None]:
        """Coordinate one online rebuild without deleting the live index first.

        Upserts executed in this context are rebuild writes. Ordinary writes in
        other tasks remain available and fence out stale rebuild writes for the
        same entity. Successful sessions retire older model identities only for
        entities actually refreshed by the session.
        """

        if self._active_rebuild_session() is not None:
            raise RuntimeError("Nested sqlite-vec rebuild sessions are not supported")

        await self._rebuild_lock.acquire()
        context_token = None
        session = None
        try:
            await self.initialize()
            async with self._coordinator.write_lock:
                coordinator = self._coordinator
                coordinator.entity_write_epochs.clear()
                async with self._db_lock:
                    db = self._require_db()
                    await self._reset_rebuild_tracking(db)
                session = _RebuildSession(
                    baseline_write_epoch=coordinator.write_epoch,
                    baseline_clear_epoch=coordinator.clear_epoch,
                )
                coordinator.current_rebuild_session = session
            context_token = self._rebuild_context.set(session)
            try:
                yield
            except BaseException:
                raise
            else:
                await self._finalize_rebuild_session(session)
        finally:
            exit_with_error = sys.exc_info()[0] is not None
            cancelled_during_cleanup = False
            cleanup_task = asyncio.create_task(self._discard_rebuild_tracking())
            while not cleanup_task.done():
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    cancelled_during_cleanup = True
                    continue
                except Exception:
                    break
            if cleanup_task.done() and not cleanup_task.cancelled():
                cleanup_error = cleanup_task.exception()
                if cleanup_error is not None:
                    logger.warning(
                        "Failed to discard sqlite-vec rebuild tracking: %s",
                        cleanup_error,
                    )
            if session is not None:
                session.active = False
                if self._coordinator.current_rebuild_session is session:
                    self._coordinator.current_rebuild_session = None
                self._coordinator.entity_write_epochs.clear()
            if context_token is not None:
                self._rebuild_context.reset(context_token)
            self._rebuild_lock.release()
            if cancelled_during_cleanup and not exit_with_error:
                raise asyncio.CancelledError

    def _active_rebuild_session(self) -> _RebuildSession | None:
        session = self._rebuild_context.get()
        return session if session is not None and session.active else None

    def in_rebuild_session(self) -> bool:
        """Return whether the current task is publishing rebuild writes."""
        return self._active_rebuild_session() is not None

    def verify_rebuild_target(
        self,
        *,
        model_key: str | None,
        dimension: int | None = None,
    ) -> None:
        """Verify the active identity immediately before rebuild finalization."""

        session = self._active_rebuild_session()
        if session is None or session.target_model_key is None:
            return
        if (
            model_key is None
            or session.target_model_key != str(model_key)
            or (
                dimension is not None
                and session.target_dimension is not None
                and session.target_dimension != int(dimension)
            )
        ):
            session.identity_changed = True
            raise EmbeddingRebuildIdentityChangedError(
                "Embedding identity changed during vector rebuild"
            )

    def _rebuild_write_is_current(self, session: _RebuildSession, entity_id: str) -> bool:
        return (
            self._coordinator.current_rebuild_session is session
            and session.active
            and self._coordinator.clear_epoch == session.baseline_clear_epoch
            and self._coordinator.entity_write_epochs.get(entity_id, 0)
            <= session.baseline_write_epoch
        )

    def _validate_rebuild_identity(
        self,
        session: _RebuildSession,
        identities: set[tuple[str, int]],
    ) -> None:
        if not identities:
            return
        if len(identities) != 1:
            session.identity_changed = True
            raise EmbeddingRebuildIdentityChangedError(
                "Embedding identity changed during vector rebuild"
            )
        model_key, dimension = next(iter(identities))
        if session.target_model_key is None:
            session.target_model_key = model_key
            session.target_dimension = dimension
            return
        if session.target_model_key != model_key or session.target_dimension != dimension:
            session.identity_changed = True
            raise EmbeddingRebuildIdentityChangedError(
                "Embedding identity changed during vector rebuild"
            )

    def _assert_rebuild_identity_stable(self, session: _RebuildSession) -> None:
        if session.identity_changed:
            raise EmbeddingRebuildIdentityChangedError(
                "Embedding identity changed during vector rebuild"
            )

    def _record_normal_writes(self, entity_ids: set[str]) -> None:
        coordinator = self._coordinator
        session = coordinator.current_rebuild_session
        if not entity_ids or session is None or not session.active:
            return
        coordinator.write_epoch += 1
        for entity_id in entity_ids:
            coordinator.entity_write_epochs[entity_id] = coordinator.write_epoch

    def _record_clear(self) -> None:
        coordinator = self._coordinator
        coordinator.write_epoch += 1
        coordinator.clear_epoch += 1
        coordinator.entity_write_epochs.clear()

    async def close(self) -> None:
        async with self._db_lock:
            if self._db is None:
                return
            await self._db.close()
            self._db = None
            self._initialized = False

    async def _ensure_registry_schema(self, db: aiosqlite.Connection) -> None:
        await db.execute(f"""
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
            """)
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{self._registry_table}_model ON {self._registry_table}(embedding_model)"
        )

    async def _reset_rebuild_tracking(self, db: aiosqlite.Connection) -> None:
        try:
            await db.execute(
                f"""
                CREATE TEMP TABLE IF NOT EXISTS {self._rebuild_marks_table} (
                    entity_id TEXT PRIMARY KEY
                )
                """
            )
            await db.execute(f"DELETE FROM {self._rebuild_marks_table}")
            await db.commit()
        except BaseException:
            await asyncio.shield(db.rollback())
            raise

    async def _prepare_rebuild_cleanup_tracking(
        self,
        db: aiosqlite.Connection,
        session: _RebuildSession,
    ) -> None:
        if session.cleanup_needed is not None:
            return
        target_model_key = session.target_model_key
        if target_model_key is None:
            session.cleanup_needed = False
            return
        async with db.execute(
            f"SELECT 1 FROM {self._registry_table} WHERE embedding_model != ? LIMIT 1",
            (target_model_key,),
        ) as cursor:
            session.cleanup_needed = await cursor.fetchone() is not None

    async def _discard_rebuild_tracking(self) -> None:
        if not self._initialized:
            return
        async with self._coordinator.write_lock:
            async with self._db_lock:
                db = self._require_db()
                try:
                    await db.execute(f"DROP TABLE IF EXISTS {self._rebuild_marks_table}")
                    await db.commit()
                except BaseException:
                    await asyncio.shield(db.rollback())
                    raise

    async def _ensure_vec_table(
        self, db: aiosqlite.Connection, table_name: str, dimension: int
    ) -> None:
        if await self._table_exists(db, table_name):
            return
        pk_clause = (
            f", {self._partition_key_column} text partition key"
            if self._partition_key_column
            else ""
        )
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

    def _embedding_model_key(self, embedding: object) -> str:
        index_identity = getattr(embedding, "index_identity", None)
        if index_identity:
            return str(index_identity)
        identity = getattr(embedding, "model_identity", None)
        if identity:
            return str(identity)
        return str(getattr(embedding, "model_name", "embedding"))

    def _sanitize_identifier(self, value: str) -> str:
        return _SAFE_IDENTIFIER.sub("_", value.lower()).strip("_")

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SqliteVecIndex is not initialized")
        return self._db


__all__ = [
    "EmbeddingRebuildIdentityChangedError",
    "SqliteVecIndex",
    "VectorSearchHit",
    "_deserialize_float32_blob",
    "sqlite_vec",
]
