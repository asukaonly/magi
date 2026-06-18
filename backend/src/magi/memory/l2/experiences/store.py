"""CRUD and membership helpers for L2 experience persistence."""

from __future__ import annotations

import json
import time
from typing import Any, Iterable

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .codec import L2ExperienceStoreBaseMixin
from .models import ExperienceMemberWrite, ExperienceSeedEvidenceWrite


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
    "source_seed_id",
    "parent_experience_id",
    "merged_into_experience_id",
    "user_label",
    "user_note",
    "user_pinned",
    "last_recomputed_at",
}
_MEMBER_TYPES = {"episode", "event"}
_MEMBER_ROLES = {"core", "supporting", "context", "excluded"}
_SEED_LIST_FIELDS = {
    "anchor_entity_ids",
    "anchor_place_ids",
    "anchor_topic_keys",
}
_ALLOWED_SEED_UPDATE_FIELDS = {
    "status",
    "title",
    "description",
    "anchor_entity_ids",
    "anchor_place_ids",
    "anchor_topic_keys",
    "time_start",
    "time_end",
    "confidence",
    "created_by",
    "source_ref_type",
    "source_ref_id",
    "promoted_experience_id",
    "last_evaluated_at",
}
_SEED_TYPES = {"manual", "project", "repeated_goal"}
_SEED_STATUSES = {"candidate", "accepted", "rejected", "promoted", "stale"}
_SEED_EVIDENCE_REF_TYPES = {"episode", "event", "entity", "summary"}
_SEED_EVIDENCE_ROLES = {"trigger", "support", "candidate", "included", "excluded", "boundary"}


def _json_list(values: list[str] | None) -> str:
    return json.dumps(values or [], ensure_ascii=False)


def _member_value(member: ExperienceMemberWrite | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(member, ExperienceMemberWrite):
        return getattr(member, key, default)
    return member.get(key, default)


def _seed_evidence_value(
    evidence: ExperienceSeedEvidenceWrite | dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    if isinstance(evidence, ExperienceSeedEvidenceWrite):
        return getattr(evidence, key, default)
    return evidence.get(key, default)


class L2ExperienceStoreMixin(L2ExperienceStoreBaseMixin):
    """Create, update, list, and curate L2 experiences."""

    async def create_experience_seed(
        self,
        *,
        seed_id: str,
        seed_type: str,
        status: str = "candidate",
        title: str | None = None,
        description: str | None = None,
        anchor_entity_ids: list[str] | None = None,
        anchor_place_ids: list[str] | None = None,
        anchor_topic_keys: list[str] | None = None,
        time_start: float | None = None,
        time_end: float | None = None,
        confidence: float = 0.0,
        created_by: str = "system",
        source_ref_type: str | None = None,
        source_ref_id: str | None = None,
    ) -> str:
        """Create a durable experience seed."""
        if seed_type not in _SEED_TYPES:
            raise ValueError(f"Unsupported experience seed_type: {seed_type}")
        if status not in _SEED_STATUSES:
            raise ValueError(f"Unsupported experience seed status: {status}")
        if not seed_id.strip():
            raise ValueError("Experience seed_id is required")
        now = time.time()
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO experience_seeds(
                    seed_id, seed_type, status, title, description,
                    anchor_entity_ids, anchor_place_ids, anchor_topic_keys,
                    time_start, time_end, confidence, created_by,
                    source_ref_type, source_ref_id, promoted_experience_id,
                    created_at, updated_at, last_evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seed_id,
                    seed_type,
                    status,
                    title,
                    description,
                    _json_list(anchor_entity_ids),
                    _json_list(anchor_place_ids),
                    _json_list(anchor_topic_keys),
                    time_start,
                    time_end,
                    confidence,
                    created_by,
                    source_ref_type,
                    source_ref_id,
                    None,
                    now,
                    now,
                    None,
                ),
            )
            await db.commit()
        return seed_id

    async def get_experience_seed(self, *, seed_id: str) -> dict[str, Any] | None:
        """Return one experience seed by ID."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM experience_seeds WHERE seed_id = ?",
                (seed_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._experience_seed_row_to_dict(row) if row else None

    async def list_experience_seeds(
        self,
        *,
        status: str | None = None,
        statuses: list[str] | None = None,
        seed_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List experience seeds with optional filters."""
        await self.initialize()
        query = "SELECT * FROM experience_seeds WHERE 1=1"
        args: list[Any] = []
        if status:
            query += " AND status = ?"
            args.append(status)
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            args.extend(statuses)
        if seed_type:
            query += " AND seed_type = ?"
            args.append(seed_type)
        query += " ORDER BY created_at DESC, updated_at DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._experience_seed_row_to_dict(row) for row in rows]

    async def update_experience_seed(self, *, seed_id: str, **fields: Any) -> bool:
        """Update mutable experience seed fields."""
        updates = {
            key: value
            for key, value in fields.items()
            if key in _ALLOWED_SEED_UPDATE_FIELDS
        }
        if not updates:
            return False
        if "status" in updates and updates["status"] not in _SEED_STATUSES:
            raise ValueError(f"Unsupported experience seed status: {updates['status']}")
        for field in _SEED_LIST_FIELDS:
            if field in updates and isinstance(updates[field], list):
                updates[field] = _json_list(updates[field])
        updates["updated_at"] = time.time()
        set_clause = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [seed_id]

        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE experience_seeds SET {set_clause} WHERE seed_id = ?",
                tuple(values),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def add_experience_seed_evidence(
        self,
        *,
        seed_id: str,
        evidence: Iterable[ExperienceSeedEvidenceWrite | dict[str, Any]],
    ) -> int:
        """Add evidence references for a seed. Returns newly inserted count."""
        await self.initialize()
        now = time.time()
        added = 0
        async with sqlite_connection_async(self.db_path) as db:
            for item in evidence:
                ref_type = str(_seed_evidence_value(item, "ref_type", "") or "").strip()
                ref_id = str(_seed_evidence_value(item, "ref_id", "") or "").strip()
                role = str(_seed_evidence_value(item, "role", "support") or "support").strip()
                confidence = float(_seed_evidence_value(item, "confidence", 0.5) or 0.0)
                reason = _seed_evidence_value(item, "reason")
                if ref_type not in _SEED_EVIDENCE_REF_TYPES:
                    raise ValueError(f"Unsupported experience seed evidence ref_type: {ref_type}")
                if role not in _SEED_EVIDENCE_ROLES:
                    raise ValueError(f"Unsupported experience seed evidence role: {role}")
                if not ref_id:
                    raise ValueError("Experience seed evidence ref_id is required")
                cursor = await db.execute(
                    """
                    INSERT OR IGNORE INTO experience_seed_evidence(
                        seed_id, ref_type, ref_id, role, confidence, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (seed_id, ref_type, ref_id, role, confidence, reason, now),
                )
                added += int(cursor.rowcount > 0)
            await db.commit()
        return added

    async def list_experience_seed_evidence(
        self,
        *,
        seed_id: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """List evidence references for a seed."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM experience_seed_evidence
                WHERE seed_id = ?
                ORDER BY
                    created_at ASC,
                    CASE role
                        WHEN 'trigger' THEN 0
                        WHEN 'included' THEN 1
                        WHEN 'support' THEN 2
                        WHEN 'candidate' THEN 3
                        WHEN 'boundary' THEN 4
                        WHEN 'excluded' THEN 5
                        ELSE 6
                    END,
                    ref_type ASC,
                    ref_id ASC
                LIMIT ?
                """,
                (seed_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._experience_seed_evidence_row_to_dict(row) for row in rows]

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
        source_seed_id: str | None = None,
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
                    source_seed_id, parent_experience_id, merged_into_experience_id,
                    user_label, user_note, user_pinned,
                    created_at, updated_at, last_recomputed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    source_seed_id,
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
