"""CRUD and membership helpers for L2 experience persistence."""

from __future__ import annotations

import json
import time
from typing import Any, Iterable

import aiosqlite

from ....core.sqlite import sqlite_connection_async, sqlite_transaction_async
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
    "user_cover_asset_ref",
    "user_pinned",
    "last_recomputed_at",
}
_EXPERIENCE_INSERT_COLUMNS = (
    "experience_id",
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
    "user_cover_asset_ref",
    "user_pinned",
    "created_at",
    "updated_at",
    "last_recomputed_at",
)
_EXPERIENCE_INSERT_SQL = f"""
    INSERT INTO experiences({", ".join(_EXPERIENCE_INSERT_COLUMNS)})
    VALUES ({", ".join("?" for _ in _EXPERIENCE_INSERT_COLUMNS)})
"""
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
_DRAFT_STATUSES = {"editing", "completed", "discarded"}
_DRAFT_JSON_FIELDS = {
    "chapters": "chapters_json",
    "possible_evidence": "possible_evidence_json",
    "excluded_evidence": "excluded_evidence_json",
}


def _json_list(values: list[str] | None) -> str:
    return json.dumps(values or [], ensure_ascii=False)


def _experience_insert_values(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _experience_insert_value(column, row.get(column))
        for column in _EXPERIENCE_INSERT_COLUMNS
    )


def _experience_insert_value(column: str, value: Any) -> Any:
    if column in _LIST_FIELDS:
        return _json_list(value)
    if column == "user_pinned":
        return 1 if value else 0
    return value


def _member_value(member: ExperienceMemberWrite | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(member, ExperienceMemberWrite):
        return getattr(member, key, default)
    return member.get(key, default)


def _experience_member_insert_values(
    members: Iterable[ExperienceMemberWrite | dict[str, Any]],
    *,
    experience_id: str,
    added_at: float,
) -> list[tuple[str, str, str, str, float, float]]:
    values: list[tuple[str, str, str, str, float, float]] = []
    seen: set[tuple[str, str]] = set()
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
        member_key = (member_type, member_id)
        if member_key in seen:
            continue
        seen.add(member_key)
        values.append(
            (
                experience_id,
                member_type,
                member_id,
                role,
                confidence,
                added_at + len(values) * 0.000001,
            )
        )
    return values


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

    async def create_experience_draft(
        self,
        *,
        draft_id: str,
        query_text: str,
        title: str,
        one_sentence_review: str,
        time_start: float,
        time_end: float,
        chapters: list[dict[str, Any]],
        possible_evidence: list[dict[str, Any]],
        excluded_evidence: list[dict[str, Any]] | None = None,
        status: str = "editing",
    ) -> str:
        """Persist one user-editable experience draft."""
        if status not in _DRAFT_STATUSES:
            raise ValueError(f"Unsupported experience draft status: {status}")
        if not draft_id.strip() or not query_text.strip() or not title.strip():
            raise ValueError("Experience draft id, query, and title are required")
        now = time.time()
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO experience_drafts(
                    draft_id, status, query_text, title, one_sentence_review,
                    time_start, time_end, chapters_json, possible_evidence_json,
                    excluded_evidence_json, created_experience_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    draft_id,
                    status,
                    query_text.strip(),
                    title.strip(),
                    one_sentence_review.strip(),
                    float(time_start),
                    float(time_end),
                    json.dumps(chapters, ensure_ascii=False),
                    json.dumps(possible_evidence, ensure_ascii=False),
                    json.dumps(excluded_evidence or [], ensure_ascii=False),
                    now,
                    now,
                ),
            )
            await db.commit()
        return draft_id

    async def get_experience_draft(self, *, draft_id: str) -> dict[str, Any] | None:
        """Return one experience draft."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM experience_drafts WHERE draft_id = ?",
                (draft_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._experience_draft_row_to_dict(row) if row else None

    async def list_experience_drafts(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List experience drafts ordered by latest edit."""
        await self.initialize()
        query = "SELECT * FROM experience_drafts WHERE 1=1"
        args: list[Any] = []
        if status:
            if status not in _DRAFT_STATUSES:
                raise ValueError(f"Unsupported experience draft status: {status}")
            query += " AND status = ?"
            args.append(status)
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._experience_draft_row_to_dict(row) for row in rows]

    async def update_experience_draft(
        self,
        *,
        draft_id: str,
        expected_updated_at: float | None = None,
        **updates: Any,
    ) -> bool:
        """Update editable draft fields, optionally guarded by its timestamp."""
        allowed = {
            "status", "query_text", "title", "one_sentence_review", "time_start",
            "time_end", "chapters", "possible_evidence", "excluded_evidence",
            "user_cover_asset_ref", "created_experience_id",
        }
        invalid = set(updates) - allowed
        if invalid:
            raise ValueError(f"Unsupported experience draft fields: {sorted(invalid)}")
        if "status" in updates and updates["status"] not in _DRAFT_STATUSES:
            raise ValueError(f"Unsupported experience draft status: {updates['status']}")
        if not updates:
            return False
        columns: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            columns.append(f"{_DRAFT_JSON_FIELDS.get(key, key)} = ?")
            values.append(
                json.dumps(value, ensure_ascii=False)
                if key in _DRAFT_JSON_FIELDS
                else value
            )
        columns.append("updated_at = ?")
        values.extend([time.time(), draft_id])
        where_clause = "draft_id = ?"
        if expected_updated_at is not None:
            where_clause += " AND updated_at = ?"
            values.append(float(expected_updated_at))
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE experience_drafts SET {', '.join(columns)} WHERE {where_clause}",
                tuple(values),
            )
            await db.commit()
        return cursor.rowcount > 0

    async def replace_experience_chapters(
        self,
        *,
        experience_id: str,
        chapters: list[dict[str, Any]],
    ) -> None:
        """Replace the user-facing chapter structure for an experience."""
        now = time.time()
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                "DELETE FROM experience_chapters WHERE experience_id = ?",
                (experience_id,),
            )
            await db.executemany(
                """
                INSERT INTO experience_chapters(
                    experience_id, chapter_id, position, title, summary,
                    time_start, time_end, episode_ids_json, event_ids_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        experience_id,
                        str(chapter.get("chapter_id") or f"chapter-{index + 1}"),
                        index,
                        str(chapter.get("title") or "").strip(),
                        str(chapter.get("summary") or "").strip(),
                        chapter.get("time_start"),
                        chapter.get("time_end"),
                        json.dumps(chapter.get("episode_ids") or [], ensure_ascii=False),
                        json.dumps(chapter.get("event_ids") or [], ensure_ascii=False),
                        now,
                        now,
                    )
                    for index, chapter in enumerate(chapters)
                ],
            )
            await db.commit()

    async def list_experience_chapters(self, *, experience_id: str) -> list[dict[str, Any]]:
        """List the durable chapter structure for an experience."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM experience_chapters
                WHERE experience_id = ?
                ORDER BY position ASC
                """,
                (experience_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._experience_chapter_row_to_dict(row) for row in rows]

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
        user_cover_asset_ref: str | None = None,
        user_pinned: bool = False,
    ) -> str:
        """Create a new experience row."""
        await self.initialize()
        now = time.time()
        row = dict(
            experience_id=experience_id, status=status, title=title,
            time_start=time_start, time_end=time_end, experience_type=experience_type,
            intent=intent, outcome=outcome, magi_interpretation=magi_interpretation,
            narrative_score=narrative_score, primary_entity_ids=primary_entity_ids,
            primary_place_ids=primary_place_ids, primary_topic_keys=primary_topic_keys,
            source_episode_count=source_episode_count, source_event_count=source_event_count,
            source_seed_id=source_seed_id, parent_experience_id=parent_experience_id,
            merged_into_experience_id=merged_into_experience_id, user_label=user_label,
            user_note=user_note, user_cover_asset_ref=user_cover_asset_ref,
            user_pinned=user_pinned, created_at=now, updated_at=now,
            last_recomputed_at=None,
        )
        await self._insert_experience_row(row)
        return experience_id

    async def _insert_experience_row(self, row: dict[str, Any]) -> None:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(_EXPERIENCE_INSERT_SQL, _experience_insert_values(row))
            await db.commit()

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
        if row is None:
            return None
        experience = self._experience_row_to_dict(row)
        experience["chapters"] = await self.list_experience_chapters(
            experience_id=experience_id
        )
        return experience

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
            for index, member in enumerate(members):
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
                    (experience_id, member_type, member_id, role, confidence, now + index * 0.000001),
                )
                added += int(cursor.rowcount > 0)
            await db.commit()
        return added

    async def replace_experience_members(
        self,
        *,
        experience_id: str,
        members: Iterable[ExperienceMemberWrite | dict[str, Any]],
    ) -> int:
        """Replace all source memberships in one transaction."""
        await self.initialize()
        values = _experience_member_insert_values(
            members,
            experience_id=experience_id,
            added_at=time.time(),
        )
        async with sqlite_transaction_async(self.db_path) as db:
            await db.execute(
                "DELETE FROM experience_members WHERE experience_id = ?",
                (experience_id,),
            )
            await db.executemany(
                """
                INSERT INTO experience_members(
                    experience_id, member_type, member_id, role, confidence, added_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        return len(values)

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
