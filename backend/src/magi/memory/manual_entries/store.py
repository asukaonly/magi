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

_EXPECTED_L1_EVENT_UNSET = object()


class ManualEntryStore:
    """Persistence layer for user-authored memory entries.

    DDL is owned by the ``memory_shared`` migration chain; this store
    reads/writes only. Cross-database L1 projection uses a durable intent:
    reserve the deterministic event identity here, write L1, then complete
    the link. Deletion sets a durable gate before cleaning memory so a
    concurrent projector cannot publish an unowned event.
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
                    deleted_at, l1_event_id, weather_json, body_doc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(entry.body_doc, ensure_ascii=False) if entry.body_doc else None,
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
        body_doc: Optional[dict] = None,
        clear_body_doc: bool = False,
        clear_weather: bool = False,
        expected_l1_event_id: object = _EXPECTED_L1_EVENT_UNSET,
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
        # body_doc uses an explicit boolean to clear, not an
        # empty-string sentinel, because the value is a JSON dict and
        # there's no natural "empty" form. The two-arg shape:
        #   body_doc=None,  clear_body_doc=False  → don't touch
        #   body_doc={...}, clear_body_doc=False  → set
        #   body_doc=None,  clear_body_doc=True   → clear to NULL
        if body_doc is not None:
            fields.append("body_doc = ?")
            values.append(json.dumps(body_doc, ensure_ascii=False))
        elif clear_body_doc:
            fields.append("body_doc = ?")
            values.append(None)
        if clear_weather:
            fields.append("weather_json = NULL")

        if not fields:
            return False

        values.append(entry_id)
        sql = (
            f"UPDATE manual_entries SET {', '.join(fields)} "
            "WHERE entry_id = ? AND deleted_at IS NULL "
            "AND delete_requested_at IS NULL "
            "AND pending_l1_event_id IS NULL"
        )
        if expected_l1_event_id is not _EXPECTED_L1_EVENT_UNSET:
            sql += " AND l1_event_id IS ?"
            values.append(expected_l1_event_id)
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(sql, tuple(values))
            await db.commit()
            return cursor.rowcount > 0

    async def reserve_l1_projection(
        self,
        entry_id: str,
        event_id: str,
        *,
        expected_previous_event_id: Optional[str],
    ) -> bool:
        """Durably own one deterministic L1 identity before writing L1.

        Repeating the same reservation is idempotent. A different pending
        identity, a projection-link change, or a requested deletion closes
        the write path before any external side effect can occur.
        """
        normalized_event_id = str(event_id).strip()
        if not normalized_event_id:
            raise ValueError("event_id must not be empty")

        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE manual_entries
                    SET pending_l1_event_id = ?,
                        pending_l1_predecessor_event_id = ?
                    WHERE entry_id = ?
                      AND deleted_at IS NULL
                      AND delete_requested_at IS NULL
                      AND l1_event_id IS ?
                      AND (
                          pending_l1_event_id IS NULL
                          OR (
                              pending_l1_event_id = ?
                              AND pending_l1_predecessor_event_id IS ?
                          )
                      )
                    """,
                    (
                        normalized_event_id,
                        expected_previous_event_id,
                        entry_id,
                        expected_previous_event_id,
                        normalized_event_id,
                        expected_previous_event_id,
                    ),
                )
                await db.commit()
                return cursor.rowcount > 0
            except BaseException:
                await db.rollback()
                raise

    async def complete_l1_projection(
        self,
        entry_id: str,
        event_id: str,
        *,
        expected_previous_event_id: Optional[str],
    ) -> bool:
        """Link a reserved L1 projection and clear its durable intent."""
        normalized_event_id = str(event_id).strip()
        if not normalized_event_id:
            raise ValueError("event_id must not be empty")

        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE manual_entries
                    SET l1_event_id = ?,
                        pending_l1_event_id = NULL,
                        pending_l1_predecessor_event_id = NULL
                    WHERE entry_id = ?
                      AND deleted_at IS NULL
                      AND delete_requested_at IS NULL
                      AND l1_event_id IS ?
                      AND pending_l1_event_id = ?
                      AND pending_l1_predecessor_event_id IS ?
                    """,
                    (
                        normalized_event_id,
                        entry_id,
                        expected_previous_event_id,
                        normalized_event_id,
                        expected_previous_event_id,
                    ),
                )
                await db.commit()
                return cursor.rowcount > 0
            except BaseException:
                await db.rollback()
                raise

    async def request_delete(self, entry_id: str, *, requested_at: float) -> bool:
        """Close all mutation/projection paths before cross-layer cleanup."""
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE manual_entries
                    SET delete_requested_at = COALESCE(delete_requested_at, ?)
                    WHERE entry_id = ? AND deleted_at IS NULL
                    """,
                    (float(requested_at), entry_id),
                )
                await db.commit()
                return cursor.rowcount > 0
            except BaseException:
                await db.rollback()
                raise

    async def finalize_delete(self, entry_id: str, *, deleted_at: float) -> bool:
        """Hide a delete-gated row only after every owned projection is gone."""
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE manual_entries
                    SET deleted_at = ?,
                        l1_event_id = NULL,
                        pending_l1_event_id = NULL,
                        pending_l1_predecessor_event_id = NULL,
                        delete_requested_at = NULL
                    WHERE entry_id = ?
                      AND deleted_at IS NULL
                      AND delete_requested_at IS NOT NULL
                    """,
                    (float(deleted_at), entry_id),
                )
                await db.commit()
                return cursor.rowcount > 0
            except BaseException:
                await db.rollback()
                raise

    async def set_weather(
        self,
        entry_id: str,
        weather: Optional[dict],
    ) -> bool:
        """Attach (or clear, when ``weather=None``) the ambient weather
        snapshot. Returns True on a row change."""
        payload = json.dumps(weather, ensure_ascii=False) if weather else None
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE manual_entries
                SET weather_json = ?
                WHERE entry_id = ?
                  AND deleted_at IS NULL
                  AND delete_requested_at IS NULL
                  AND pending_l1_event_id IS NULL
                """,
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
        sql = "SELECT * FROM manual_entries WHERE event_at >= ? AND event_at <= ?"
        args: list = [float(time_start), float(time_end)]
        if not include_deleted:
            sql += " AND deleted_at IS NULL AND delete_requested_at IS NULL"
        sql += " ORDER BY event_at ASC LIMIT ?"
        args.append(int(limit))

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_entry(row) for row in rows]

    async def list_recovery_candidates(
        self,
        *,
        after_entry_id: str | None = None,
        limit: int = 100,
    ) -> list[ManualEntry]:
        """Page active rows with an incomplete projection or deletion."""
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        sql = """
            SELECT *
            FROM manual_entries
            WHERE deleted_at IS NULL
              AND (
                  delete_requested_at IS NOT NULL
                  OR pending_l1_event_id IS NOT NULL
                  OR l1_event_id IS NULL
              )
        """
        args: list[object] = []
        if after_entry_id is not None:
            sql += " AND entry_id > ?"
            args.append(str(after_entry_id))
        sql += " ORDER BY entry_id ASC LIMIT ?"
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
        # body_doc (migration 0009) — same defensive read pattern.
        body_doc: Optional[dict] = None
        try:
            raw_doc = row["body_doc"] if "body_doc" in row.keys() else None
            if raw_doc:
                parsed = json.loads(raw_doc)
                if isinstance(parsed, dict):
                    body_doc = parsed
        except (ValueError, TypeError, IndexError):
            body_doc = None
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
            pending_l1_event_id=row["pending_l1_event_id"],
            pending_l1_predecessor_event_id=row["pending_l1_predecessor_event_id"],
            delete_requested_at=row["delete_requested_at"],
            weather=weather,
            body_doc=body_doc,
        )
