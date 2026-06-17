"""CRUD and membership helpers for L2 experience persistence."""

from __future__ import annotations

import json
import time
from typing import Any, Iterable

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .codec import L2ExperienceStoreBaseMixin
from .models import ExperienceMemberWrite


_LIST_FIELDS = {
    "primary_entity_ids",
    "primary_place_ids",
    "primary_topic_keys",
}
_ALLOWED_UPDATE_FIELDS = {
    "status",
    "title",
    "time_start",
    "time_end",
    "experience_type",
    "intent",
    "outcome",
    "magi_interpretation",
    "narrative_score",
    "primary_entity_ids",
    "primary_place_ids",
    "primary_topic_keys",
    "source_episode_count",
    "source_event_count",
    "parent_experience_id",
    "merged_into_experience_id",
    "user_label",
    "user_note",
    "user_pinned",
    "last_recomputed_at",
}
_MEMBER_TYPES = {"episode", "event"}
_MEMBER_ROLES = {"core", "supporting", "context", "excluded"}


def _json_list(values: list[str] | None) -> str:
    return json.dumps(values or [], ensure_ascii=False)


def _member_value(member: ExperienceMemberWrite | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(member, ExperienceMemberWrite):
        return getattr(member, key, default)
    return member.get(key, default)


class L2ExperienceStoreMixin(L2ExperienceStoreBaseMixin):
    """Create, update, list, and curate L2 experiences."""

    async def create_experience(
        self,
        *,
        experience_id: str,
        time_start: float,
        time_end: float,
        status: str = "candidate",
        title: str | None = None,
        experience_type: str | None = None,
        intent: str | None = None,
        outcome: str | None = None,
        magi_interpretation: str | None = None,
        narrative_score: float = 0.0,
        primary_entity_ids: list[str] | None = None,
        primary_place_ids: list[str] | None = None,
        primary_topic_keys: list[str] | None = None,
        source_episode_count: int = 0,
        source_event_count: int = 0,
        parent_experience_id: str | None = None,
        merged_into_experience_id: str | None = None,
        user_label: str | None = None,
        user_note: str | None = None,
        user_pinned: bool = False,
    ) -> str:
        """Create a new experience row."""
        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO experiences(
                    experience_id, status, title, time_start, time_end,
                    experience_type, intent, outcome, magi_interpretation,
                    narrative_score, primary_entity_ids, primary_place_ids,
                    primary_topic_keys, source_episode_count, source_event_count,
                    parent_experience_id, merged_into_experience_id,
                    user_label, user_note, user_pinned,
                    created_at, updated_at, last_recomputed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experience_id,
                    status,
                    title,
                    time_start,
                    time_end,
                    experience_type,
                    intent,
                    outcome,
                    magi_interpretation,
                    narrative_score,
                    _json_list(primary_entity_ids),
                    _json_list(primary_place_ids),
                    _json_list(primary_topic_keys),
                    source_episode_count,
                    source_event_count,
                    parent_experience_id,
                    merged_into_experience_id,
                    user_label,
                    user_note,
                    1 if user_pinned else 0,
                    now,
                    now,
                    None,
                ),
            )
            await db.commit()
        return experience_id

    async def get_experience(self, *, experience_id: str) -> dict[str, Any] | None:
        """Return one experience by ID."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM experiences WHERE experience_id = ?",
                (experience_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._experience_row_to_dict(row) if row else None

    async def list_experiences(
        self,
        *,
        status: str | None = None,
        statuses: list[str] | None = None,
        time_start: float | None = None,
        time_end: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List experiences with optional status and time-window filters."""
        await self.initialize()
        query = "SELECT * FROM experiences WHERE 1=1"
        args: list[Any] = []
        if status:
            query += " AND status = ?"
            args.append(status)
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            args.extend(statuses)
        if time_start is not None:
            query += " AND time_end >= ?"
            args.append(time_start)
        if time_end is not None:
            query += " AND time_start <= ?"
            args.append(time_end)
        query += " ORDER BY time_start DESC, time_end DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._experience_row_to_dict(row) for row in rows]

    async def update_experience(self, *, experience_id: str, **fields: Any) -> bool:
        """Update mutable experience fields."""
        updates = {key: value for key, value in fields.items() if key in _ALLOWED_UPDATE_FIELDS}
        if not updates:
            return False
        for field in _LIST_FIELDS:
            if field in updates and isinstance(updates[field], list):
                updates[field] = _json_list(updates[field])
        if "user_pinned" in updates:
            updates["user_pinned"] = 1 if updates["user_pinned"] else 0
        updates["updated_at"] = time.time()
        set_clause = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [experience_id]

        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE experiences SET {set_clause} WHERE experience_id = ?",
                tuple(values),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def add_experience_members(
        self,
        *,
        experience_id: str,
        members: Iterable[ExperienceMemberWrite | dict[str, Any]],
    ) -> int:
        """Add source episode/event memberships. Returns newly inserted count."""
        await self.initialize()
        now = time.time()
        added = 0
        async with sqlite_connection_async(self.db_path) as db:
            for member in members:
                member_type = str(_member_value(member, "member_type", "") or "").strip()
                member_id = str(_member_value(member, "member_id", "") or "").strip()
                role = str(_member_value(member, "role", "core") or "core").strip()
                confidence = float(_member_value(member, "confidence", 0.5) or 0.0)
                if member_type not in _MEMBER_TYPES:
                    raise ValueError(f"Unsupported experience member_type: {member_type}")
                if role not in _MEMBER_ROLES:
                    raise ValueError(f"Unsupported experience member role: {role}")
                if not member_id:
                    raise ValueError("Experience member_id is required")
                cursor = await db.execute(
                    """
                    INSERT OR IGNORE INTO experience_members(
                        experience_id, member_type, member_id, role, confidence, added_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (experience_id, member_type, member_id, role, confidence, now),
                )
                added += int(cursor.rowcount > 0)
            await db.commit()
        return added

    async def list_experience_members(
        self, *, experience_id: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        """List source memberships for an experience."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM experience_members
                WHERE experience_id = ?
                ORDER BY added_at ASC
                LIMIT ?
                """,
                (experience_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._experience_member_row_to_dict(row) for row in rows]

    async def count_experience_members(self, *, experience_id: str) -> int:
        """Count non-excluded source memberships for an experience."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT COUNT(*) FROM experience_members
                WHERE experience_id = ? AND role != 'excluded'
                """,
                (experience_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def recompute_experience_counts(self, *, experience_id: str) -> dict[str, int]:
        """Recompute source episode and distinct source event counts."""
        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT COUNT(DISTINCT member_id)
                FROM experience_members
                WHERE experience_id = ?
                  AND member_type = 'episode'
                  AND role != 'excluded'
                """,
                (experience_id,),
            ) as cursor:
                episode_row = await cursor.fetchone()
            async with db.execute(
                """
                SELECT COUNT(DISTINCT source_event_id)
                FROM (
                    SELECT ee.event_id AS source_event_id
                    FROM experience_members em
                    JOIN episode_events ee ON ee.episode_id = em.member_id
                    WHERE em.experience_id = ?
                      AND em.member_type = 'episode'
                      AND em.role != 'excluded'
                    UNION
                    SELECT em.member_id AS source_event_id
                    FROM experience_members em
                    WHERE em.experience_id = ?
                      AND em.member_type = 'event'
                      AND em.role != 'excluded'
                )
                """,
                (experience_id, experience_id),
            ) as cursor:
                event_row = await cursor.fetchone()
            source_episode_count = int(episode_row[0]) if episode_row else 0
            source_event_count = int(event_row[0]) if event_row else 0
            await db.execute(
                """
                UPDATE experiences
                SET source_episode_count = ?,
                    source_event_count = ?,
                    last_recomputed_at = ?,
                    updated_at = ?
                WHERE experience_id = ?
                """,
                (source_episode_count, source_event_count, now, now, experience_id),
            )
            await db.commit()
        return {
            "source_episode_count": source_episode_count,
            "source_event_count": source_event_count,
        }


__all__ = ["L2ExperienceStoreMixin"]
