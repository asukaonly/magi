"""Persistent per-sensor state store (L9 - Awareness layer)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable, Protocol

from ..core.sqlite import sqlite_connection_async


class SensorStateStore(Protocol):
    """Persistent state for sensor sync bookkeeping."""

    async def get_cursor(self, sensor_id: str) -> str | None: ...

    async def set_cursor(self, sensor_id: str, cursor: str) -> None: ...

    async def get_known_fingerprints(self, sensor_id: str, *, limit: int = 10000) -> set[str]: ...

    async def add_fingerprints(self, sensor_id: str, fingerprints: Iterable[str]) -> None: ...

    async def prune_fingerprints(self, sensor_id: str, *, keep_latest: int = 10000) -> int: ...

    async def get_stats(self, sensor_id: str) -> dict[str, Any]: ...

    async def update_stats(self, sensor_id: str, delta: dict[str, Any]) -> None: ...


_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS sensor_cursors (
    sensor_id TEXT PRIMARY KEY,
    cursor_value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sensor_fingerprints (
    sensor_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (sensor_id, fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_sensor_fp_created
    ON sensor_fingerprints (sensor_id, created_at);

CREATE TABLE IF NOT EXISTS sensor_stats (
    sensor_id TEXT PRIMARY KEY,
    stats_json TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL
);
"""


class SqliteSensorStateStore:
    """SQLite-backed implementation of SensorStateStore."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._initialized = False

    async def _ensure_schema(self) -> None:
        if self._initialized:
            return
        async with sqlite_connection_async(self._db_path) as db:
            await db.executescript(_SCHEMA_SQL)
            await db.commit()
        self._initialized = True

    async def get_cursor(self, sensor_id: str) -> str | None:
        await self._ensure_schema()
        async with sqlite_connection_async(self._db_path) as db:
            row = await db.execute_fetchall(
                "SELECT cursor_value FROM sensor_cursors WHERE sensor_id = ?",
                (sensor_id,),
            )
            if row:
                return str(row[0][0]) if row[0][0] is not None else None
        return None

    async def set_cursor(self, sensor_id: str, cursor: str) -> None:
        await self._ensure_schema()
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute(
                "INSERT INTO sensor_cursors (sensor_id, cursor_value, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(sensor_id) DO UPDATE SET cursor_value = excluded.cursor_value, updated_at = excluded.updated_at",
                (sensor_id, cursor, now),
            )
            await db.commit()

    async def get_known_fingerprints(self, sensor_id: str, *, limit: int = 10000) -> set[str]:
        await self._ensure_schema()
        async with sqlite_connection_async(self._db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT fingerprint FROM sensor_fingerprints "
                "WHERE sensor_id = ? ORDER BY created_at DESC LIMIT ?",
                (sensor_id, limit),
            )
            return {str(r[0]) for r in rows}

    async def add_fingerprints(self, sensor_id: str, fingerprints: Iterable[str]) -> None:
        await self._ensure_schema()
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            await db.executemany(
                "INSERT OR IGNORE INTO sensor_fingerprints (sensor_id, fingerprint, created_at) "
                "VALUES (?, ?, ?)",
                [(sensor_id, fp, now) for fp in fingerprints],
            )
            await db.commit()

    async def prune_fingerprints(self, sensor_id: str, *, keep_latest: int = 10000) -> int:
        await self._ensure_schema()
        async with sqlite_connection_async(self._db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT COUNT(*) FROM sensor_fingerprints WHERE sensor_id = ?",
                (sensor_id,),
            )
            total = int(rows[0][0]) if rows else 0
            if total <= keep_latest:
                return 0
            to_delete = total - keep_latest
            await db.execute(
                "DELETE FROM sensor_fingerprints WHERE rowid IN ("
                "  SELECT rowid FROM sensor_fingerprints "
                "  WHERE sensor_id = ? ORDER BY created_at ASC LIMIT ?"
                ")",
                (sensor_id, to_delete),
            )
            await db.commit()
            return to_delete

    async def get_stats(self, sensor_id: str) -> dict[str, Any]:
        await self._ensure_schema()
        async with sqlite_connection_async(self._db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT stats_json FROM sensor_stats WHERE sensor_id = ?",
                (sensor_id,),
            )
            if rows and rows[0][0]:
                return json.loads(rows[0][0])
        return {}

    async def update_stats(self, sensor_id: str, delta: dict[str, Any]) -> None:
        await self._ensure_schema()
        current = await self.get_stats(sensor_id)
        current.update(delta)
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute(
                "INSERT INTO sensor_stats (sensor_id, stats_json, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(sensor_id) DO UPDATE SET stats_json = excluded.stats_json, updated_at = excluded.updated_at",
                (sensor_id, json.dumps(current), now),
            )
            await db.commit()
