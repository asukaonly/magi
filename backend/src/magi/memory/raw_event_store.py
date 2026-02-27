"""
Memory Storage - L1Raw event Storage（RawEventStore）
Internal note.
"""
import aiosqlite
import json
import logging
import uuid
from typing import Optional
from pathlib import Path
from ..events.events import Event

logger = logging.getLogger(__name__)


class RawEventStore:
    """
    Internal note.

    Internal note.
    Internal note.
    Internal note.
    Internal note.
    """

    def __init__(
        self,
        db_path: str = "~/.magi/data/event_store.db",
        media_dir: str = "~/.magi/data/events",
    ):
        """
        initializeRaw event Storage

        Args:
            db_path: databasefilepath
            Internal note.
        """
        self.db_path = db_path
        self.media_dir = media_dir

    @property
    def _expanded_db_path(self) -> str:
        """get expanded database path (process ~)"""
        return str(Path(self.db_path).expanduser())

    @property
    def _expanded_media_dir(self) -> str:
        """get展开后的媒体directorypath（process ~）"""
        return str(Path(self.media_dir).expanduser())

    async def init(self):
        """initializedatabase"""
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self._expanded_media_dir).mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # check if table exists and if schema is correct
            cursor = await db.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='event_store'
            """)
            table_exists = await cursor.fetchone()

            if table_exists:
                # check if has type column
                cursor = await db.execute("PRAGMA table_info(event_store)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]

                # Internal note.
                required_columns = {'id', 'type', 'data', 'timestamp', 'source', 'level', 'correlation_id', 'metadata', 'created_at'}
                if not required_columns.issubset(set(column_names)):
                    logger.warning(f"event store table schema incompatible, recreating... Existing columns: {column_names}")
                    await db.execute("DROP table IF EXISTS event_store")
                    await db.execute("DROP index IF EXISTS idx_event_store_type")
                    await db.execute("DROP index IF EXISTS idx_event_store_timestamp")

            # createeventtable
            await db.execute("""
                create table IF NOT EXISTS event_store (
                    id TEXT primary key,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    media_path TEXT,
                    timestamp real NOT NULL,
                    source TEXT,
                    level intEGER,
                    correlation_id TEXT,
                    metadata TEXT,
                    created_at real NOT NULL
                )
            """)

            # createindex
            await db.execute("""
                create index IF NOT EXISTS idx_event_store_type
                ON event_store(type)
            """)
            await db.execute("""
                create index IF NOT EXISTS idx_event_store_timestamp
                ON event_store(timestamp)
            """)
            await db.commit()

    async def store(self, event: Event) -> str:
        """
        storageevent

        Args:
            event: eventObject

        Returns:
            eventid
        """
        import time

        # Internal note.
        media_path = None
        if hasattr(event, 'media') and event.media:
            media_path = await self._save_media(event.media)

        # Internal note.
        event_id = str(uuid.uuid4())
        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute("""
                INSERT intO event_store (
                    id, Type, data, media_path, timestamp, source,
                    level, correlation_id, metadata, created_at
                ) valueS (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id,
                event.type,
                json.dumps(event.data),
                media_path,
                event.timestamp,
                event.source,
                event.level.value,
                event.correlation_id,
                json.dumps(event.metadata),
                time.time(),
            ))
            await db.commit()

        return event_id

    async def get_event(self, event_id: str) -> Optional[Event]:
        """
        getevent

        Args:
            event_id: eventid

        Returns:
            Internal note.
        """
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM event_store WHERE id = ?",
                (event_id,)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return self._row_to_event(row)

    async def get_events_by_type(
        self,
        event_type: str,
        limit: int = 100,
    ) -> list[Event]:
        """
        Internal note.

        Args:
            event_type: eventtype
            limit: maximumReturnquantity

        Returns:
            eventlist
        """
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("""
                SELECT * FROM event_store
                WHERE type = ?
                order BY timestamp DESC
                LIMIT ?
            """, (event_type, limit))

            rows = await cursor.fetchall()
            return [self._row_to_event(row) for row in rows]

    async def get_events_by_time_range(
        self,
        start_time: float,
        end_time: float,
        limit: int = 100,
    ) -> list[Event]:
        """
        Internal note.

        Args:
            Internal note.
            Internal note.
            limit: maximumReturnquantity

        Returns:
            eventlist
        """
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("""
                SELECT * FROM event_store
                WHERE timestamp >= ? AND timestamp <= ?
                order BY timestamp DESC
                LIMIT ?
            """, (start_time, end_time, limit))

            rows = await cursor.fetchall()
            return [self._row_to_event(row) for row in rows]

    async def _save_media(self, media) -> str:
        """
        Internal note.

        Args:
            Internal note.

        Returns:
            Internal note.
        """
        from datetime import datetime

        # generationfilepath
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{uuid.uuid4()}.{media.extension}"
        path = f"{self._expanded_media_dir}/{date_str}/{filename}"

        # Internal note.
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        # savefile
        with open(path, "wb") as f:
            f.write(media.data)

        return path

    def _row_to_event(self, row) -> Event:
        """将databaserowconvert为eventObject"""
        return Event(
            type=row[1],
            data=json.loads(row[2]),
            timestamp=row[4],
            source=row[5],
            level=row[6],  # eventlevelisint枚举
            correlation_id=row[7],
            metadata=json.loads(row[8]) if row[8] else {},
        )
