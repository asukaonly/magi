"""Persistent per-sensor state store (L9 - Awareness layer)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from ..core.sqlite import sqlite_connection_async

logger = logging.getLogger(__name__)


class SensorStateStore(Protocol):
    """Persistent state for sensor sync bookkeeping."""

    async def get_cursor(self, sensor_id: str) -> str | None: ...

    async def set_cursor(self, sensor_id: str, cursor: str) -> None: ...

    async def get_known_fingerprints(self, sensor_id: str, *, limit: int = 10000) -> set[str]: ...

    async def add_fingerprints(self, sensor_id: str, fingerprints: Iterable[str]) -> None: ...

    async def add_fingerprint_groups(self, fingerprints_by_sensor: Mapping[str, Iterable[str]]) -> None: ...

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
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
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
        await self.add_fingerprint_groups({sensor_id: fingerprints})

    async def add_fingerprint_groups(self, fingerprints_by_sensor: Mapping[str, Iterable[str]]) -> None:
        await self._ensure_schema()
        now = time.time()
        rows = [
            (sensor_id, fingerprint, now)
            for sensor_id, fingerprints in fingerprints_by_sensor.items()
            for fingerprint in set(fingerprints)
            if fingerprint
        ]
        if not rows:
            return
        async with sqlite_connection_async(self._db_path) as db:
            await db.executemany(
                "INSERT OR IGNORE INTO sensor_fingerprints (sensor_id, fingerprint, created_at) "
                "VALUES (?, ?, ?)",
                rows,
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


@dataclass(frozen=True, slots=True)
class _SensorFingerprintWrite:
    sensor_id: str
    fingerprint: str


_STOP = object()


class SensorStateWriteQueue:
    """Bounded batch writer for high-volume sensor fingerprints."""

    def __init__(
        self,
        *,
        sensor_state_store: SensorStateStore,
        max_queue_size: int = 10000,
        max_batch_size: int = 250,
        flush_interval_seconds: float = 0.25,
        retry_attempts: int = 2,
    ) -> None:
        self._state_store = sensor_state_store
        self._max_batch_size = max(1, int(max_batch_size))
        self._flush_interval_seconds = max(0.001, float(flush_interval_seconds))
        self._retry_attempts = max(0, int(retry_attempts))
        self._queue: asyncio.Queue[_SensorFingerprintWrite | object] = asyncio.Queue(
            maxsize=max(1, int(max_queue_size))
        )
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._run(), name="sensor-state-write-queue")

    async def stop(self) -> None:
        task = self._worker_task
        if task is None:
            return
        if task.done():
            await task
            self._worker_task = None
            return
        await self.drain()
        await self._queue.put(_STOP)
        await self._queue.join()
        await task
        self._worker_task = None

    async def drain(self) -> None:
        task = self._worker_task
        if task is None:
            return
        if task.done():
            await task
            return
        await self._queue.join()

    async def add_fingerprint(self, sensor_id: str, fingerprint: str) -> None:
        if self._worker_task is None or self._worker_task.done():
            raise RuntimeError("SensorStateWriteQueue is not running")
        normalized_sensor_id = str(sensor_id or "").strip()
        normalized_fingerprint = str(fingerprint or "").strip()
        if not normalized_sensor_id or not normalized_fingerprint:
            return
        await self._queue.put(
            _SensorFingerprintWrite(
                sensor_id=normalized_sensor_id,
                fingerprint=normalized_fingerprint,
            )
        )

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            if item is _STOP:
                self._queue.task_done()
                return

            batch = [item]
            should_stop = False
            deadline = asyncio.get_running_loop().time() + self._flush_interval_seconds

            while len(batch) < self._max_batch_size:
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break
                try:
                    next_item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if next_item is _STOP:
                    self._queue.task_done()
                    should_stop = True
                    break
                batch.append(next_item)

            try:
                await self._flush_batch(batch)
            finally:
                for _ in batch:
                    self._queue.task_done()

            if should_stop:
                return

    async def _flush_batch(self, batch: list[_SensorFingerprintWrite | object]) -> None:
        groups: dict[str, set[str]] = defaultdict(set)
        for item in batch:
            if isinstance(item, _SensorFingerprintWrite):
                groups[item.sensor_id].add(item.fingerprint)
        if not groups:
            return

        for attempt in range(self._retry_attempts + 1):
            try:
                await self._state_store.add_fingerprint_groups(groups)
                return
            except Exception:
                if attempt >= self._retry_attempts:
                    logger.exception(
                        "sensor_state fingerprint batch failed (items=%s sensors=%s)",
                        sum(len(fingerprints) for fingerprints in groups.values()),
                        len(groups),
                    )
                    return
                logger.warning(
                    "sensor_state fingerprint batch retrying (attempt=%s)",
                    attempt + 1,
                    exc_info=True,
                )
                await asyncio.sleep(min(1.0, 0.05 * (2**attempt)))
