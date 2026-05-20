"""CRUD + soft-delete for manual_entries."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from .models import ManualEntry


class ManualEntryStore:
    """Persistence layer for user-authored memory entries.

    DDL is owned by migration 0007_manual_entries; this store reads/writes
    only. Soft-delete is implemented via ``deleted_at`` — list_window
    excludes deleted by default; explicit ``include_deleted`` brings them
    back for the (admin / debugging) use case.
    """

    def __init__(self, *, db_path: str) -> None:
        self.db_path = str(Path(db_path).expanduser())

    async def create(self, entry: ManualEntry) -> str:
        entry_id = entry.entry_id or f"me-{uuid.uuid4().hex[:12]}"
        created_at = entry.created_at or time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO manual_entries(
                    entry_id, created_at, event_at, kind, body,
                    mood, location_label, location_lat, location_lng,
                    attachments_json, exclude_from_llm, user_pinned,
                    deleted_at, l1_event_id, weather_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    float(created_at),
                    float(entry.event_at),
                    entry.kind,
                    entry.body,
                    entry.mood,
                    entry.location_label,
                    entry.location_lat,
                    entry.location_lng,
                    json.dumps(entry.attachments or [], ensure_ascii=False),
                    1 if entry.exclude_from_llm else 0,
                    1 if entry.user_pinned else 0,
                    entry.deleted_at,
                    entry.l1_event_id,
                    json.dumps(entry.weather, ensure_ascii=False) if entry.weather else None,
                ),
            )
            await db.commit()
        return entry_id

    async def update(
        self,
        entry_id: str,
        *,
        body: Optional[str] = None,
        mood: Optional[str] = None,
        event_at: Optional[float] = None,
        attachments: Optional[list[str]] = None,
        user_pinned: Optional[bool] = None,
        exclude_from_llm: Optional[bool] = None,
        location_label: Optional[str] = None,
    ) -> bool:
        """Partial update. Returns True if a row was changed.

        Fields left as ``None`` are not touched. Two text fields (mood,
        location_label) follow an empty-string-clears convention:
          - ``None``  → don't touch
          - ``""``    → clear to SQL NULL
          - other str → set to that value
        This lets the HTTP body distinguish "not in payload" from
        "explicitly clear" without a separate flag column.
        """
        fields: list[str] = []
        values: list = []
        if body is not None:
            fields.append("body = ?")
            values.append(body)
        if mood is not None:
            fields.append("mood = ?")
            values.append(mood or None)  # empty string → NULL
        if event_at is not None:
            fields.append("event_at = ?")
            values.append(float(event_at))
        if attachments is not None:
            fields.append("attachments_json = ?")
            values.append(json.dumps(attachments, ensure_ascii=False))
        if user_pinned is not None:
            fields.append("user_pinned = ?")
            values.append(1 if user_pinned else 0)
        if exclude_from_llm is not None:
            fields.append("exclude_from_llm = ?")
            values.append(1 if exclude_from_llm else 0)
        if location_label is not None:
            fields.append("location_label = ?")
            values.append(location_label or None)  # empty string → NULL

        if not fields:
            return False

        values.append(entry_id)
        sql = f"UPDATE manual_entries SET {', '.join(fields)} WHERE entry_id = ?"
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(sql, tuple(values))
            await db.commit()
            return cursor.rowcount > 0

    async def soft_delete(self, entry_id: str) -> bool:
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE manual_entries SET deleted_at = ? WHERE entry_id = ? AND deleted_at IS NULL",
                (time.time(), entry_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def link_l1_event(self, entry_id: str, l1_event_id: str) -> None:
        """Store the L1 event id assigned by the projector — used so later
        edits can re-issue the same L1 row instead of orphaning one."""
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                "UPDATE manual_entries SET l1_event_id = ? WHERE entry_id = ?",
                (l1_event_id, entry_id),
            )
            await db.commit()

    async def set_weather(
        self, entry_id: str, weather: Optional[dict],
    ) -> bool:
        """Attach (or clear, when ``weather=None``) the ambient weather
        snapshot. Returns True on a row change."""
        payload = json.dumps(weather, ensure_ascii=False) if weather else None
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE manual_entries SET weather_json = ? WHERE entry_id = ?",
                (payload, entry_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get(self, entry_id: str) -> Optional[ManualEntry]:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM manual_entries WHERE entry_id = ?",
                (entry_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_entry(row) if row else None

    async def list_window(
        self,
        *,
        time_start: float,
        time_end: float,
        include_deleted: bool = False,
        limit: int = 500,
    ) -> list[ManualEntry]:
        sql = (
            "SELECT * FROM manual_entries WHERE event_at >= ? AND event_at <= ?"
        )
        args: list = [float(time_start), float(time_end)]
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        sql += " ORDER BY event_at ASC LIMIT ?"
        args.append(int(limit))

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_entry(row) for row in rows]

    @staticmethod
    def _row_to_entry(row) -> ManualEntry:
        try:
            attachments = json.loads(row["attachments_json"] or "[]")
            if not isinstance(attachments, list):
                attachments = []
        except (ValueError, TypeError):
            attachments = []
        # weather_json is a new column (migration 0008). Use a defensive
        # access so reads against an unpatched test DB don't crash —
        # aiosqlite.Row supports `in` via .keys().
        weather: Optional[dict] = None
        try:
            raw = row["weather_json"] if "weather_json" in row.keys() else None
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    weather = parsed
        except (ValueError, TypeError, IndexError):
            weather = None
        return ManualEntry(
            entry_id=str(row["entry_id"]),
            created_at=float(row["created_at"]),
            event_at=float(row["event_at"]),
            kind=str(row["kind"]),
            body=str(row["body"]),
            mood=row["mood"],
            location_label=row["location_label"],
            location_lat=row["location_lat"],
            location_lng=row["location_lng"],
            attachments=[str(a) for a in attachments],
            exclude_from_llm=bool(row["exclude_from_llm"]),
            user_pinned=bool(row["user_pinned"]),
            deleted_at=row["deleted_at"],
            l1_event_id=row["l1_event_id"],
            weather=weather,
        )
