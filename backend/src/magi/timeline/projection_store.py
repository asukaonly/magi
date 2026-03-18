"""SQLite-backed cache store for timeline projection items."""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from .projection_models import TimelineProjectionItem


class TimelineProjectionStore:
    """Persist lazy-generated timeline items by query window."""

    def __init__(self, *, db_path: str) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS timeline_projection_items (
                    item_id TEXT PRIMARY KEY,
                    window_key TEXT NOT NULL,
                    filter_hash TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    time_start REAL NOT NULL,
                    time_end REAL NOT NULL,
                    sort_time REAL NOT NULL,
                    primary_event_id TEXT,
                    primary_summary_id TEXT,
                    source_event_ids TEXT NOT NULL,
                    source_summary_ids TEXT NOT NULL,
                    display_payload TEXT NOT NULL,
                    projection_version INTEGER NOT NULL,
                    generated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_timeline_projection_window
                ON timeline_projection_items(window_key, filter_hash, projection_version, sort_time DESC);
                """
            )
            await db.commit()
        self._initialized = True

    async def load_items(
        self,
        *,
        window_key: str,
        filter_hash: str,
        projection_version: int,
        limit: int,
    ) -> list[TimelineProjectionItem]:
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM timeline_projection_items
                WHERE window_key = ? AND filter_hash = ? AND projection_version = ?
                ORDER BY sort_time DESC, generated_at DESC
                LIMIT ?
                """,
                (window_key, filter_hash, projection_version, int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_item(row) for row in rows]

    async def save_items(
        self,
        *,
        window_key: str,
        filter_hash: str,
        projection_version: int,
        items: list[TimelineProjectionItem],
    ) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                DELETE FROM timeline_projection_items
                WHERE window_key = ? AND filter_hash = ? AND projection_version = ?
                """,
                (window_key, filter_hash, projection_version),
            )
            if items:
                await db.executemany(
                    """
                    INSERT INTO timeline_projection_items(
                        item_id, window_key, filter_hash, item_type, time_start, time_end,
                        sort_time, primary_event_id, primary_summary_id, source_event_ids,
                        source_summary_ids, display_payload, projection_version, generated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.item_id,
                            item.window_key,
                            item.filter_hash,
                            item.item_type,
                            float(item.time_start),
                            float(item.time_end),
                            float(item.sort_time),
                            item.primary_event_id,
                            item.primary_summary_id,
                            json.dumps(item.source_event_ids, ensure_ascii=False),
                            json.dumps(item.source_summary_ids, ensure_ascii=False),
                            json.dumps(item.display_payload, ensure_ascii=False),
                            int(item.projection_version),
                            float(item.generated_at),
                        )
                        for item in items
                    ],
                )
            await db.commit()

    async def invalidate_window(
        self,
        *,
        window_key: str,
        filter_hash: str,
        projection_version: int | None = None,
    ) -> int:
        await self.initialize()
        query = """
            DELETE FROM timeline_projection_items
            WHERE window_key = ? AND filter_hash = ?
        """
        args: list[object] = [window_key, filter_hash]
        if projection_version is not None:
            query += " AND projection_version = ?"
            args.append(int(projection_version))
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(query, tuple(args))
            await db.commit()
        return int(cursor.rowcount or 0)

    @staticmethod
    def _row_to_item(row: aiosqlite.Row) -> TimelineProjectionItem:
        return TimelineProjectionItem(
            item_id=str(row["item_id"]),
            window_key=str(row["window_key"]),
            filter_hash=str(row["filter_hash"]),
            item_type=str(row["item_type"]),
            time_start=float(row["time_start"]),
            time_end=float(row["time_end"]),
            sort_time=float(row["sort_time"]),
            primary_event_id=row["primary_event_id"],
            primary_summary_id=row["primary_summary_id"],
            source_event_ids=json.loads(row["source_event_ids"] or "[]"),
            source_summary_ids=json.loads(row["source_summary_ids"] or "[]"),
            display_payload=json.loads(row["display_payload"] or "{}"),
            projection_version=int(row["projection_version"]),
            generated_at=float(row["generated_at"]),
        )


__all__ = ["TimelineProjectionStore"]
