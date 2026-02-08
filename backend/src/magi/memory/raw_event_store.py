"""
记忆存储 - L1原始事件存储（RawEventStore）
完整的非结构化事件信息
"""
import aiosqlite
import json
import uuid
from typing import Optional
from pathlib import Path
import time
from ..events.events import Event


class RawEventStore:
    """
    L1原始事件存储 - 完整事件信息

    特点：
    - 保留事件完整数据（时间戳、类型、数据、元数据）
    - 永不清除（作为事件溯源的基础）
    - 支持媒体文件（图片、音频路径）
    """

    def __init__(
        self,
        db_path: str = "./data/memories/events.db",
        media_dir: str = "./data/events",
    ):
        """
        初始化原始事件存储

        Args:
            db_path: 数据库文件路径
            media_dir: 媒体文件目录
        """
        self.db_path = db_path
        self.media_dir = media_dir

    async def init(self):
        """初始化数据库"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.media_dir).mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            # 创建事件表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    media_path TEXT,
                    timestamp REAL NOT NULL,
                    source TEXT,
                    level INTEGER,
                    correlation_id TEXT,
                    metadata TEXT,
                    created_at REAL NOT NULL
                )
            """)

            # 创建索引
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_type
                ON events(type)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_timestamp
                ON events(timestamp)
            """)
            await db.commit()

    async def store(self, event: Event) -> str:
        """
        存储事件

        Args:
            event: 事件对象

        Returns:
            事件ID
        """
        import time

        # 处理媒体文件（如果有的话）
        media_path = None
        if hasattr(event, 'media') and event.media:
            media_path = await self._save_media(event.media)

        # 存储到SQLite
        event_id = str(uuid.uuid4())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO events (
                    id, type, data, media_path, timestamp, source,
                    level, correlation_id, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        获取事件

        Args:
            event_id: 事件ID

        Returns:
            事件对象或None
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM events WHERE id = ?",
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
        按类型获取事件

        Args:
            event_type: 事件类型
            limit: 最大返回数量

        Returns:
            事件列表
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT * FROM events
                WHERE type = ?
                ORDER BY timestamp DESC
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
        按时间范围获取事件

        Args:
            start_time: 开始时间
            end_time: 结束时间
            limit: 最大返回数量

        Returns:
            事件列表
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT * FROM events
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (start_time, end_time, limit))

            rows = await cursor.fetchall()
            return [self._row_to_event(row) for row in rows]

    async def _save_media(self, media) -> str:
        """
        保存媒体文件（按日期组织）

        Args:
            media: 媒体对象

        Returns:
            媒体文件路径
        """
        from datetime import datetime

        # 生成文件路径
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{uuid.uuid4()}.{media.extension}"
        path = f"{self.media_dir}/{date_str}/{filename}"

        # 确保目录存在
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        # 保存文件
        with open(path, "wb") as f:
            f.write(media.data)

        return path

    def _row_to_event(self, row) -> Event:
        """将数据库行转换为Event对象"""
        return Event(
            type=row[1],
            data=json.loads(row[2]),
            timestamp=row[4],
            source=row[5],
            level=row[6],  # EventLevel是int枚举
            correlation_id=row[7],
            metadata=json.loads(row[8]) if row[8] else {},
        )
