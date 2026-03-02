"""L1 raw event store with SQLite persistence and optional media file storage."""

from __future__ import annotations

import csv
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from ..events.events import Event, EventLevel

logger = logging.getLogger(__name__)


class RawEventStore:
    """Stores full-fidelity events for traceability and replay."""

    def __init__(self, db_path: str = "~/.magi/data/events.db", media_dir: str = "~/.magi/data/events"):
        self.db_path = db_path
        self.media_dir = media_dir

    @property
    def _expanded_db_path(self) -> str:
        return str(Path(self.db_path).expanduser())

    @property
    def _expanded_media_dir(self) -> str:
        return str(Path(self.media_dir).expanduser())

    async def init(self) -> None:
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self._expanded_media_dir).mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS event_store (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    media_path TEXT,
                    timestamp REAL NOT NULL,
                    source TEXT,
                    level INTEGER NOT NULL,
                    correlation_id TEXT,
                    metadata TEXT,
                    created_at REAL NOT NULL
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_event_store_type ON event_store(type)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_event_store_timestamp ON event_store(timestamp)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_event_store_correlation ON event_store(correlation_id)")
            await db.commit()

    async def store(self, event: Event) -> str:
        media_path = None
        if getattr(event, "media", None):
            media_path = await self._save_media(event.media)

        event_id = str(uuid.uuid4())
        level_value = event.level.value if hasattr(event.level, "value") else int(event.level)
        payload = event.data if isinstance(event.data, (dict, list, str, int, float, bool)) else str(event.data)

        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                """
                INSERT INTO event_store(
                    id, type, data, media_path, timestamp, source,
                    level, correlation_id, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event.type,
                    json.dumps(payload, ensure_ascii=False),
                    media_path,
                    float(event.timestamp),
                    event.source,
                    int(level_value),
                    event.correlation_id,
                    json.dumps(event.metadata or {}, ensure_ascii=False),
                    time.time(),
                ),
            )
            await db.commit()

        return event_id

    async def delete_event(self, event_id: str) -> bool:
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("DELETE FROM event_store WHERE id = ?", (event_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def get_event(self, event_id: str) -> Optional[Event]:
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                """
                SELECT type, data, timestamp, source, level, correlation_id, metadata
                FROM event_store
                WHERE id = ?
                """,
                (event_id,),
            )
            row = await cursor.fetchone()

        return self._row_to_event(row) if row else None

    async def list_events(self, limit: int = 100, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        query = (
            "SELECT id, type, data, timestamp, source, level, correlation_id, metadata, created_at "
            "FROM event_store"
        )
        args: List[Any] = []
        if event_type:
            query += " WHERE type = ?"
            args.append(event_type)
        query += " ORDER BY timestamp DESC LIMIT ?"
        args.append(limit)

        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(query, tuple(args))
            rows = await cursor.fetchall()

        events = []
        for row in rows:
            events.append(
                {
                    "id": row[0],
                    "type": row[1],
                    "data": json.loads(row[2]) if row[2] else {},
                    "timestamp": float(row[3]),
                    "source": row[4],
                    "level": int(row[5]),
                    "correlation_id": row[6],
                    "metadata": json.loads(row[7]) if row[7] else {},
                    "created_at": float(row[8]),
                }
            )
        return events

    async def get_events_by_type(self, event_type: str, limit: int = 100) -> List[Event]:
        events = await self.list_events(limit=limit, event_type=event_type)
        return [self._dict_to_event(event) for event in events]

    async def get_events_by_time_range(self, start_time: float, end_time: float, limit: int = 1000) -> List[Event]:
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                """
                SELECT type, data, timestamp, source, level, correlation_id, metadata
                FROM event_store
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (float(start_time), float(end_time), int(limit)),
            )
            rows = await cursor.fetchall()

        return [self._row_to_event(row) for row in rows]

    async def replay_events(
        self,
        start_time: float,
        end_time: float,
        publisher,
        speed: float = 1.0,
    ) -> int:
        """Replays events in chronological order into a callback/publisher."""
        events = await self.get_events_by_time_range(start_time, end_time, limit=100000)
        if not events:
            return 0

        count = 0
        previous_timestamp: Optional[float] = None
        for event in events:
            if previous_timestamp is not None and speed > 0:
                delta = max(0.0, float(event.timestamp) - previous_timestamp)
                await _async_sleep(delta / max(speed, 0.001))
            previous_timestamp = float(event.timestamp)
            await publisher(event)
            count += 1

        return count

    async def export_events(self, start_time: float, end_time: float, fmt: str = "json") -> str:
        events = await self.list_events(limit=100000)
        filtered = [
            item
            for item in events
            if float(start_time) <= float(item.get("timestamp", 0.0)) <= float(end_time)
        ]

        export_dir = Path(self._expanded_db_path).parent / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if fmt.lower() == "csv":
            path = export_dir / f"events_{timestamp}.csv"
            with path.open("w", newline="", encoding="utf-8") as fp:
                writer = csv.DictWriter(
                    fp,
                    fieldnames=[
                        "id",
                        "type",
                        "timestamp",
                        "source",
                        "level",
                        "correlation_id",
                        "data",
                        "metadata",
                    ],
                )
                writer.writeheader()
                for event in filtered:
                    writer.writerow(
                        {
                            "id": event["id"],
                            "type": event["type"],
                            "timestamp": event["timestamp"],
                            "source": event["source"],
                            "level": event["level"],
                            "correlation_id": event["correlation_id"],
                            "data": json.dumps(event["data"], ensure_ascii=False),
                            "metadata": json.dumps(event["metadata"], ensure_ascii=False),
                        }
                    )
        else:
            path = export_dir / f"events_{timestamp}.json"
            path.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")

        return str(path)

    async def count_events(self) -> int:
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM event_store")
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def clear(self) -> int:
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM event_store")
            row = await cursor.fetchone()
            count = int(row[0]) if row else 0
            await db.execute("DELETE FROM event_store")
            await db.commit()
        return count

    async def _save_media(self, media: Any) -> str:
        extension = getattr(media, "extension", "bin")
        payload = getattr(media, "data", b"")

        date_folder = datetime.now().strftime("%Y-%m-%d")
        filename = f"{uuid.uuid4()}.{extension}"
        path = Path(self._expanded_media_dir) / date_folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return str(path)

    def _row_to_event(self, row: tuple) -> Event:
        return Event(
            type=str(row[0]),
            data=json.loads(row[1]) if row[1] else {},
            timestamp=float(row[2]),
            source=str(row[3] or "unknown"),
            level=EventLevel(int(row[4])),
            correlation_id=row[5],
            metadata=json.loads(row[6]) if row[6] else {},
        )

    def _dict_to_event(self, payload: Dict[str, Any]) -> Event:
        return Event(
            type=str(payload.get("type", "unknown")),
            data=payload.get("data", {}),
            timestamp=float(payload.get("timestamp", time.time())),
            source=str(payload.get("source", "unknown")),
            level=EventLevel(int(payload.get("level", EventLevel.INFO))),
            correlation_id=payload.get("correlation_id"),
            metadata=dict(payload.get("metadata", {})),
        )


async def _async_sleep(seconds: float) -> None:
    import asyncio

    if seconds <= 0:
        return
    await asyncio.sleep(seconds)
