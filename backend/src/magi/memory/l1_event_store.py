"""Canonical L1 event store for normalized memory events."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from ..events.events import Event, EventLevel
from ..timeline.contracts import TimelineEvent
from .event_contracts import MemoryEvent, normalize_runtime_event


class L1EventStore:
    """Stores immutable normalized memory events in SQLite."""

    def __init__(self, *, db_path: str = "~/.magi/data/events.db") -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        """Create the canonical L1 schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    correlation_id TEXT NOT NULL,
                    parent_event_id TEXT,
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_item_id TEXT,
                    memory_domain TEXT NOT NULL,
                    ingest_target TEXT NOT NULL,
                    cognition_eligible INTEGER NOT NULL DEFAULT 0,
                    tom_depth TEXT NOT NULL DEFAULT 'none',
                    retention_class TEXT NOT NULL DEFAULT 'compressible',
                    session_id TEXT,
                    user_id TEXT,
                    task_id TEXT,
                    goal_id TEXT,
                    raw_content TEXT NOT NULL,
                    structured_payload TEXT,
                    metadata TEXT,
                    importance_score REAL NOT NULL DEFAULT 0.5,
                    importance_t0_base REAL,
                    importance_t1_score REAL,
                    importance_version INTEGER NOT NULL DEFAULT 1,
                    level INTEGER NOT NULL DEFAULT 1,
                    media_path TEXT,
                    deleted_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
                CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
                CREATE INDEX IF NOT EXISTS idx_events_domain ON events(memory_domain);
                CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
                CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
                CREATE INDEX IF NOT EXISTS idx_events_goal ON events(goal_id);
                CREATE INDEX IF NOT EXISTS idx_events_importance ON events(importance_score DESC);
                CREATE INDEX IF NOT EXISTS idx_events_retention ON events(retention_class);
                """
            )
            await db.commit()

        self._initialized = True

    async def store(self, event: MemoryEvent) -> str:
        """Persist a normalized memory event."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO events(
                    event_id, correlation_id, parent_event_id, timestamp, created_at,
                    event_type, source, source_item_id, memory_domain, ingest_target,
                    cognition_eligible, tom_depth, retention_class, session_id, user_id,
                    task_id, goal_id, raw_content, structured_payload, metadata,
                    importance_score, importance_t0_base, importance_t1_score, importance_version,
                    level, media_path, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.correlation_id,
                    event.parent_event_id,
                    float(event.timestamp),
                    float(event.created_at),
                    event.event_type,
                    event.source,
                    event.source_item_id,
                    event.memory_domain,
                    event.ingest_target,
                    1 if event.cognition_eligible else 0,
                    event.tom_depth,
                    event.retention_class,
                    event.session_id,
                    event.user_id,
                    event.task_id,
                    event.goal_id,
                    event.raw_content,
                    event.structured_payload,
                    event.metadata,
                    float(event.importance_score),
                    float(event.importance_t0_base),
                    event.importance_t1_score,
                    int(event.importance_version),
                    int(event.level),
                    event.media_path,
                    None,
                ),
            )
            await db.commit()
        return event.event_id

    async def store_timeline_event(self, event: TimelineEvent) -> str:
        """Normalize a timeline event into the L1 schema."""
        timeline_payload = event.to_dict()
        runtime_event = Event(
            type="TIMELINE_EVENT",
            data={
                "title": event.title,
                "summary": event.summary,
                "content_blocks": timeline_payload["content_blocks"],
                "entities": event.entities,
                "tags": event.tags,
            },
            timestamp=event.occurred_at,
            source=event.source_type,
            level=EventLevel.INFO,
            correlation_id=event.event_id,
            metadata={
                "timeline": timeline_payload,
                "processing_status": event.processing_status,
                "raw_payload_ref": event.raw_payload_ref,
            },
        )
        memory_event = normalize_runtime_event(runtime_event, event_id=event.event_id)
        return await self.store(memory_event)

    async def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single event by id."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)) as cursor:
                row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def list_events(self, *, limit: int = 100, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List the newest events, optionally constrained by event type."""
        return await self.query_events(event_type=event_type, limit=limit)

    async def query_events(
        self,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        memory_domain: Optional[str] = None,
        event_type: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query events with SQL-level filters."""
        await self.initialize()
        query = "SELECT * FROM events WHERE deleted_at IS NULL"
        args: List[Any] = []

        if session_id:
            query += " AND session_id = ?"
            args.append(session_id)
        if user_id:
            query += " AND user_id = ?"
            args.append(user_id)
        if memory_domain:
            query += " AND memory_domain = ?"
            args.append(memory_domain)
        if event_type:
            query += " AND event_type = ?"
            args.append(event_type)
        if source_filters:
            placeholders = ", ".join("?" for _ in source_filters)
            query += f" AND source IN ({placeholders})"
            args.extend(source_filters)
        if cognition_eligible is not None:
            query += " AND cognition_eligible = ?"
            args.append(1 if cognition_eligible else 0)
        if start_time is not None:
            query += " AND timestamp >= ?"
            args.append(float(start_time))
        if end_time is not None:
            query += " AND timestamp <= ?"
            args.append(float(end_time))

        query += " ORDER BY timestamp DESC LIMIT ?"
        args.append(int(limit))

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def get_timeline_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Return the original timeline payload for a timeline event."""
        payload = await self.get_event(event_id)
        if payload is None:
            return None
        timeline = payload.get("metadata", {}).get("timeline")
        return timeline if isinstance(timeline, dict) else None

    async def list_timeline_events(self, *, limit: int = 100, source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List timeline events with optional source filtering."""
        events = await self.query_events(event_type="TIMELINE_EVENT", limit=limit)
        items: List[Dict[str, Any]] = []
        for event in events:
            timeline = event.get("metadata", {}).get("timeline")
            if not isinstance(timeline, dict):
                continue
            if source_type and timeline.get("source_type") != source_type:
                continue
            items.append(timeline)
        return items

    async def count_events(self) -> int:
        """Count all non-deleted events."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM events WHERE deleted_at IS NULL") as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def clear(self) -> int:
        """Delete all events and return the removed count."""
        count = await self.count_events()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM events")
            await db.commit()
        return count

    async def mark_deleted(self, event_id: str, *, deleted_at: Optional[float] = None) -> bool:
        """Soft-delete an event."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE events SET deleted_at = ? WHERE event_id = ?",
                (float(deleted_at or time.time()), event_id),
            )
            await db.commit()
        return cursor.rowcount > 0

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "event_id": str(row["event_id"]),
            "correlation_id": str(row["correlation_id"]),
            "parent_event_id": row["parent_event_id"],
            "timestamp": float(row["timestamp"]),
            "created_at": float(row["created_at"]),
            "event_type": str(row["event_type"]),
            "source": str(row["source"]),
            "source_item_id": row["source_item_id"],
            "memory_domain": str(row["memory_domain"]),
            "ingest_target": str(row["ingest_target"]),
            "cognition_eligible": bool(row["cognition_eligible"]),
            "tom_depth": str(row["tom_depth"]),
            "retention_class": str(row["retention_class"]),
            "session_id": row["session_id"],
            "user_id": row["user_id"],
            "task_id": row["task_id"],
            "goal_id": row["goal_id"],
            "raw_content": str(row["raw_content"]),
            "structured_payload": json.loads(row["structured_payload"] or "{}"),
            "metadata": json.loads(row["metadata"] or "{}"),
            "importance_score": float(row["importance_score"]),
            "importance_t0_base": float(row["importance_t0_base"] or 0.0),
            "importance_t1_score": float(row["importance_t1_score"]) if row["importance_t1_score"] is not None else None,
            "importance_version": int(row["importance_version"]),
            "level": int(row["level"]),
            "media_path": row["media_path"],
            "deleted_at": float(row["deleted_at"]) if row["deleted_at"] is not None else None,
        }


__all__ = ["L1EventStore"]
