"""CRUD and membership helpers for L2 experience persistence."""

from __future__ import annotations

import json
import time
from typing import Any, Iterable

import aiosqlite

from ....core.sqlite import sqlite_connection_async, sqlite_transaction_async
from ...source_event_governance import (
    normalize_source_event_ids,
    source_event_time_range_block_ids,
    source_event_time_range_block_predicate,
    source_event_tombstone_ids,
)
from .codec import L2ExperienceStoreBaseMixin
from .models import ExperienceMemberWrite, ExperienceSeedEvidenceWrite
from .source_event_forgetting import (
    collect_experience_draft_source_references,
    delete_experience_drafts_for_source_events,
)

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
_DERIVABLE_EXPERIENCE_STATUSES = {"candidate", "active"}
_DERIVABLE_SEED_STATUSES = {"candidate", "accepted"}
_DRAFT_JSON_FIELDS = {
    "chapters": "chapters_json",
    "possible_evidence": "possible_evidence_json",
    "excluded_evidence": "excluded_evidence_json",
}


def _active_event_reference_predicate(event_id_sql: str) -> str:
    """Return SQL that keeps L1 while rejecting forgotten derived use."""
    return f"""
        NOT EXISTS (
            SELECT 1
            FROM memory_source_event_tombstones AS source_tombstones
            WHERE source_tombstones.event_id = {event_id_sql}
        )
        AND NOT EXISTS (
            SELECT 1
            FROM memory_projection_blocks AS time_blocks
            WHERE time_blocks.event_id = {event_id_sql}
              AND {source_event_time_range_block_predicate("time_blocks")}
        )
    """


def _active_episode_reference_predicate(episode_id_sql: str) -> str:
    """Return SQL for an active episode whose evidence remains derivable."""
    return f"""
        EXISTS (
            SELECT 1
            FROM episodes AS governed_episode
            WHERE governed_episode.episode_id = {episode_id_sql}
              AND governed_episode.status = 'active'
              AND NOT EXISTS (
                  SELECT 1
                  FROM memory_projection_blocks AS episode_blocks
                  WHERE episode_blocks.block_kind = 'episode_formation'
                    AND episode_blocks.target_id = governed_episode.episode_id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM episode_events AS governed_member
                  WHERE governed_member.episode_id = governed_episode.episode_id
                    AND NOT ({_active_event_reference_predicate("governed_member.event_id")})
              )
        )
    """


def _active_summary_reference_predicate(summary_id_sql: str) -> str:
    """Return SQL for a current summary with no governed source occurrence."""
    return f"""
        EXISTS (
            SELECT 1
            FROM summaries AS governed_summary
            WHERE governed_summary.summary_id = {summary_id_sql}
              AND governed_summary.derivation_state = 'current'
              AND json_valid(governed_summary.source_event_ids)
              AND json_type(governed_summary.source_event_ids) = 'array'
              AND NOT EXISTS (
                  SELECT 1
                  FROM json_each(governed_summary.source_event_ids) AS summary_source
                  WHERE summary_source.type != 'text'
                     OR TRIM(CAST(summary_source.value AS TEXT)) = ''
                     OR NOT ({_active_event_reference_predicate("TRIM(CAST(summary_source.value AS TEXT))")})
              )
        )
    """


def _active_source_reference_predicate(ref_type_sql: str, ref_id_sql: str) -> str:
    """Return SQL for supported experience source reference kinds."""
    return f"""
        (
            ({ref_type_sql} = 'event' AND {_active_event_reference_predicate(ref_id_sql)})
            OR ({ref_type_sql} = 'episode' AND {_active_episode_reference_predicate(ref_id_sql)})
            OR ({ref_type_sql} = 'summary' AND {_active_summary_reference_predicate(ref_id_sql)})
            OR {ref_type_sql} NOT IN ('event', 'episode', 'summary')
        )
    """


def _active_member_predicate(alias: str) -> str:
    return _active_source_reference_predicate(
        f"{alias}.member_type",
        f"{alias}.member_id",
    )


def _active_seed_evidence_predicate(alias: str) -> str:
    return _active_source_reference_predicate(
        f"{alias}.ref_type",
        f"{alias}.ref_id",
    )


def _active_experience_predicate(alias: str) -> str:
    """Hide an experience while any included source is governed."""
    return f"""
        (
        {alias}.status NOT IN ('candidate', 'active')
        OR (
        NOT EXISTS (
            SELECT 1
            FROM experience_members AS governed_member
            WHERE governed_member.experience_id = {alias}.experience_id
              AND governed_member.role != 'excluded'
              AND NOT ({_active_member_predicate("governed_member")})
        )
        AND NOT EXISTS (
            SELECT 1
            FROM experience_chapters AS governed_chapter
            WHERE governed_chapter.experience_id = {alias}.experience_id
              AND (
                  NOT json_valid(governed_chapter.event_ids_json)
                  OR json_type(governed_chapter.event_ids_json) != 'array'
                  OR NOT json_valid(governed_chapter.episode_ids_json)
                  OR json_type(governed_chapter.episode_ids_json) != 'array'
                  OR EXISTS (
                      SELECT 1
                      FROM json_each(governed_chapter.event_ids_json) AS chapter_event
                      WHERE chapter_event.type != 'text'
                         OR TRIM(CAST(chapter_event.value AS TEXT)) = ''
                         OR NOT ({_active_event_reference_predicate("TRIM(CAST(chapter_event.value AS TEXT))")})
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM json_each(governed_chapter.episode_ids_json) AS chapter_episode
                      WHERE chapter_episode.type != 'text'
                         OR TRIM(CAST(chapter_episode.value AS TEXT)) = ''
                         OR NOT ({_active_episode_reference_predicate("TRIM(CAST(chapter_episode.value AS TEXT))")})
                  )
              )
        )
        )
        )
    """


async def _event_references_are_active(
    db: aiosqlite.Connection,
    event_ids: Iterable[str],
) -> bool:
    normalized = normalize_source_event_ids(event_ids)
    if not normalized:
        return True
    return not (
        await source_event_tombstone_ids(db, normalized)
        or await source_event_time_range_block_ids(db, normalized)
    )


async def _episode_references_are_active(
    db: aiosqlite.Connection,
    episode_ids: Iterable[str],
) -> bool:
    for episode_id in normalize_source_event_ids(episode_ids):
        async with db.execute(
            f"SELECT 1 WHERE {_active_episode_reference_predicate('?')}",
            (episode_id,),
        ) as cursor:
            if await cursor.fetchone() is None:
                return False
    return True


async def _draft_row_is_active(db: aiosqlite.Connection, row: aiosqlite.Row) -> bool:
    try:
        chapters = json.loads(row["chapters_json"])
        possible_evidence = json.loads(row["possible_evidence_json"])
        excluded_evidence = json.loads(row["excluded_evidence_json"])
        episode_ids, event_ids = collect_experience_draft_source_references(
            chapters=chapters,
            possible_evidence=possible_evidence,
            excluded_evidence=excluded_evidence,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return await _event_references_are_active(
        db,
        event_ids,
    ) and await _episode_references_are_active(db, episode_ids)


async def _seed_row_is_active(db: aiosqlite.Connection, row: aiosqlite.Row) -> bool:
    ref_type = str(row["source_ref_type"] or "").strip()
    ref_id = str(row["source_ref_id"] or "").strip()
    try:
        if ref_type == "episode_group":
            if not await _episode_references_are_active(db, ref_id.split(",")):
                return False
        elif ref_type in {"episode", "event", "summary"}:
            await _assert_source_reference_is_active(db, ref_type=ref_type, ref_id=ref_id)
    except ValueError:
        return False
    async with db.execute(
        f"""
        SELECT 1
        FROM experience_seed_evidence AS governed_evidence
        WHERE governed_evidence.seed_id = ?
          AND governed_evidence.role != 'excluded'
          AND NOT ({_active_seed_evidence_predicate("governed_evidence")})
        LIMIT 1
        """,
        (str(row["seed_id"]),),
    ) as cursor:
        return await cursor.fetchone() is None


async def _assert_source_reference_is_active(
    db: aiosqlite.Connection,
    *,
    ref_type: str,
    ref_id: str,
) -> None:
    """Reject terminal or forgotten source references inside the write transaction."""
    normalized_ref_id = str(ref_id or "").strip()
    if not normalized_ref_id:
        raise ValueError("Experience source reference is required")
    if ref_type == "episode":
        async with db.execute(
            f"""
            SELECT 1
            WHERE {_active_episode_reference_predicate("?")}
            """,
            (normalized_ref_id,),
        ) as cursor:
            if await cursor.fetchone() is None:
                raise ValueError(f"Episode is not active: {normalized_ref_id}")
        return
    if ref_type == "event":
        if await source_event_tombstone_ids(
            db,
            [normalized_ref_id],
        ) or await source_event_time_range_block_ids(db, [normalized_ref_id]):
            raise ValueError(f"Event has been forgotten: {normalized_ref_id}")
        return
    if ref_type == "summary":
        async with db.execute(
            f"SELECT 1 WHERE {_active_summary_reference_predicate('?')}",
            (normalized_ref_id,),
        ) as cursor:
            if await cursor.fetchone() is None:
                raise ValueError(f"Summary is not active: {normalized_ref_id}")


async def _assert_episode_group_is_active(
    db: aiosqlite.Connection,
    source_ref_id: str,
) -> None:
    episode_ids = [
        episode_id.strip()
        for episode_id in str(source_ref_id or "").split(",")
        if episode_id.strip()
    ]
    if not episode_ids:
        raise ValueError("Experience episode group is empty")
    for episode_id in episode_ids:
        await _assert_source_reference_is_active(
            db,
            ref_type="episode",
            ref_id=episode_id,
        )


async def _assert_seed_is_promotable(
    db: aiosqlite.Connection,
    *,
    seed_id: str,
) -> None:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT status, source_ref_type, source_ref_id
        FROM experience_seeds WHERE seed_id = ?
        """,
        (seed_id,),
    ) as cursor:
        seed = await cursor.fetchone()
    if seed is None or str(seed["status"] or "") not in {"candidate", "accepted"}:
        raise ValueError(f"Experience seed is not promotable: {seed_id}")

    source_ref_type = str(seed["source_ref_type"] or "").strip()
    source_ref_id = str(seed["source_ref_id"] or "").strip()
    if source_ref_type == "episode_group":
        await _assert_episode_group_is_active(db, source_ref_id)
    elif source_ref_type in {"episode", "event", "summary"}:
        await _assert_source_reference_is_active(
            db,
            ref_type=source_ref_type,
            ref_id=source_ref_id,
        )

    async with db.execute(
        """
        SELECT ref_type, ref_id
        FROM experience_seed_evidence
        WHERE seed_id = ? AND role != 'excluded'
        """,
        (seed_id,),
    ) as cursor:
        evidence_rows = await cursor.fetchall()
    for row in evidence_rows:
        ref_type = str(row["ref_type"] or "")
        if ref_type in {"episode", "event", "summary"}:
            await _assert_source_reference_is_active(
                db,
                ref_type=ref_type,
                ref_id=str(row["ref_id"] or ""),
            )


async def _assert_seed_reference_is_active(
    db: aiosqlite.Connection,
    *,
    seed_id: str,
) -> None:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT * FROM experience_seeds WHERE seed_id = ?",
        (seed_id,),
    ) as cursor:
        seed = await cursor.fetchone()
    if (
        seed is None
        or str(seed["status"] or "") in {"rejected", "stale"}
        or not await _seed_row_is_active(db, seed)
    ):
        raise ValueError(f"Experience seed is not active: {seed_id}")


async def _experience_source_seed_is_active(
    db: aiosqlite.Connection,
    row: aiosqlite.Row,
) -> bool:
    seed_id = str(row["source_seed_id"] or "").strip()
    if not seed_id:
        return True
    try:
        await _assert_seed_reference_is_active(db, seed_id=seed_id)
    except ValueError:
        return False
    return True


async def _experience_row_is_active(
    db: aiosqlite.Connection,
    *,
    experience_id: str,
    require_derivable: bool = False,
) -> bool:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        f"""
        SELECT * FROM experiences AS experience
        WHERE experience.experience_id = ?
          AND {_active_experience_predicate("experience")}
        """,
        (experience_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return False
    status = str(row["status"] or "")
    if status not in _DERIVABLE_EXPERIENCE_STATUSES:
        return not require_derivable
    return await _experience_source_seed_is_active(db, row)


async def _assert_member_sources_are_active(
    db: aiosqlite.Connection,
    members: Iterable[ExperienceMemberWrite | dict[str, Any]],
) -> None:
    for member in members:
        member_type = str(_member_value(member, "member_type", "") or "").strip()
        member_id = str(_member_value(member, "member_id", "") or "").strip()
        if member_type in {"episode", "event"}:
            await _assert_source_reference_is_active(
                db,
                ref_type=member_type,
                ref_id=member_id,
            )


async def _assert_draft_sources_are_active(
    db: aiosqlite.Connection,
    *,
    chapters: Any,
    possible_evidence: Any,
    excluded_evidence: Any,
) -> None:
    episode_ids, event_ids = collect_experience_draft_source_references(
        chapters=chapters,
        possible_evidence=possible_evidence,
        excluded_evidence=excluded_evidence,
    )
    for episode_id in sorted(episode_ids):
        await _assert_source_reference_is_active(
            db,
            ref_type="episode",
            ref_id=episode_id,
        )
    for event_id in sorted(event_ids):
        await _assert_source_reference_is_active(
            db,
            ref_type="event",
            ref_id=event_id,
        )


def _json_list(values: list[str] | None) -> str:
    return json.dumps(values or [], ensure_ascii=False)


def _experience_insert_values(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _experience_insert_value(column, row.get(column)) for column in _EXPERIENCE_INSERT_COLUMNS
    )


def _experience_insert_value(column: str, value: Any) -> Any:
    if column in _LIST_FIELDS:
        return _json_list(value)
    if column == "user_pinned":
        return 1 if value else 0
    return value


def _member_value(
    member: ExperienceMemberWrite | dict[str, Any], key: str, default: Any = None
) -> Any:
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

    async def summary_sources_are_active(
        self,
        *,
        db: aiosqlite.Connection,
        experience_id: str | None,
        episode_ids: Iterable[str],
    ) -> bool:
        """Check summary sources inside the caller's write transaction."""
        normalized_episode_ids = tuple(
            dict.fromkeys(
                str(episode_id).strip() for episode_id in episode_ids if str(episode_id).strip()
            )
        )
        normalized_experience_id = str(experience_id or "").strip()
        if normalized_experience_id:
            async with db.execute(
                f"""
                SELECT 1 FROM experiences AS experience
                WHERE experience.experience_id = ? AND experience.status = 'active'
                  AND {_active_experience_predicate("experience")}
                """,
                (normalized_experience_id,),
            ) as cursor:
                if await cursor.fetchone() is None:
                    return False
        if not normalized_episode_ids:
            return True

        episode_json = json.dumps(
            normalized_episode_ids,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        active_episode_predicate = _active_episode_reference_predicate("episode.episode_id")
        if normalized_experience_id:
            query = f"""
                SELECT COUNT(DISTINCT episode.episode_id)
                FROM episodes AS episode
                JOIN experience_members AS member
                  ON member.member_type = 'episode'
                 AND member.member_id = episode.episode_id
                WHERE episode.status = 'active'
                  AND {active_episode_predicate}
                  AND member.experience_id = ?
                  AND member.role != 'excluded'
                  AND episode.episode_id IN (
                      SELECT CAST(value AS TEXT) FROM json_each(?)
                  )
            """
            args: tuple[Any, ...] = (normalized_experience_id, episode_json)
        else:
            query = f"""
                SELECT COUNT(DISTINCT episode.episode_id)
                FROM episodes AS episode
                WHERE episode.status = 'active'
                  AND {active_episode_predicate}
                  AND episode.episode_id IN (
                      SELECT CAST(value AS TEXT) FROM json_each(?)
                  )
            """
            args = (episode_json,)
        async with db.execute(query, args) as cursor:
            row = await cursor.fetchone()
        return bool(row and int(row[0]) == len(normalized_episode_ids))

    async def validate_experience_sources(
        self,
        *,
        episode_ids: Iterable[str] = (),
        event_ids: Iterable[str] = (),
    ) -> None:
        """Fail when selected evidence is terminal or globally forgotten."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                for episode_id in dict.fromkeys(str(item).strip() for item in episode_ids):
                    if episode_id:
                        await _assert_source_reference_is_active(
                            db,
                            ref_type="episode",
                            ref_id=episode_id,
                        )
                for event_id in dict.fromkeys(str(item).strip() for item in event_ids):
                    if event_id:
                        await _assert_source_reference_is_active(
                            db,
                            ref_type="event",
                            ref_id=event_id,
                        )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def forget_experience_drafts_for_source_events(
        self,
        event_ids: Iterable[str],
    ) -> int:
        """Delete drafts whose copied evidence includes deleted source events."""
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return 0
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                deleted = await delete_experience_drafts_for_source_events(
                    db,
                    event_ids=normalized,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return deleted

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
            await db.execute("BEGIN IMMEDIATE")
            try:
                await _assert_draft_sources_are_active(
                    db,
                    chapters=chapters,
                    possible_evidence=possible_evidence,
                    excluded_evidence=excluded_evidence or [],
                )
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
            except BaseException:
                await db.rollback()
                raise
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
            if row is not None and not await _draft_row_is_active(db, row):
                row = None
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
        query += " ORDER BY updated_at DESC"
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
            active_rows = [row for row in rows if await _draft_row_is_active(db, row)]
        page = active_rows[max(0, int(offset)) : max(0, int(offset)) + max(1, int(limit))]
        return [self._experience_draft_row_to_dict(row) for row in page]

    async def update_experience_draft(
        self,
        *,
        draft_id: str,
        expected_updated_at: float | None = None,
        expected_status: str | None = None,
        **updates: Any,
    ) -> bool:
        """Update editable draft fields, optionally guarded by its timestamp."""
        allowed = {
            "status",
            "query_text",
            "title",
            "one_sentence_review",
            "time_start",
            "time_end",
            "chapters",
            "possible_evidence",
            "excluded_evidence",
            "user_cover_asset_ref",
            "created_experience_id",
        }
        invalid = set(updates) - allowed
        if invalid:
            raise ValueError(f"Unsupported experience draft fields: {sorted(invalid)}")
        if "status" in updates and updates["status"] not in _DRAFT_STATUSES:
            raise ValueError(f"Unsupported experience draft status: {updates['status']}")
        if not updates:
            return False
        reference_updates = {key: updates[key] for key in _DRAFT_JSON_FIELDS if key in updates}
        columns: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            columns.append(f"{_DRAFT_JSON_FIELDS.get(key, key)} = ?")
            values.append(
                json.dumps(value, ensure_ascii=False) if key in _DRAFT_JSON_FIELDS else value
            )
        columns.append("updated_at = ?")
        values.extend([time.time(), draft_id])
        where_clause = "draft_id = ?"
        if expected_updated_at is not None:
            where_clause += " AND updated_at = ?"
            values.append(float(expected_updated_at))
        if expected_status is not None:
            where_clause += " AND status = ?"
            values.append(str(expected_status))
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    """
                    SELECT chapters_json, possible_evidence_json,
                           excluded_evidence_json
                    FROM experience_drafts WHERE draft_id = ?
                    """,
                    (draft_id,),
                ) as current_cursor:
                    current = await current_cursor.fetchone()
                if current is None:
                    await db.rollback()
                    return False
                try:
                    reference_fields = {
                        "chapters": json.loads(current[0]),
                        "possible_evidence": json.loads(current[1]),
                        "excluded_evidence": json.loads(current[2]),
                    }
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("Experience draft evidence is malformed") from exc
                reference_fields.update(reference_updates)
                await _assert_draft_sources_are_active(db, **reference_fields)
                cursor = await db.execute(
                    f"UPDATE experience_drafts SET {', '.join(columns)} WHERE {where_clause}",
                    tuple(values),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return bool(cursor.rowcount > 0)

    async def replace_experience_chapters(
        self,
        *,
        experience_id: str,
        chapters: list[dict[str, Any]],
        expected_status: str | None = None,
    ) -> bool:
        """Replace the user-facing chapter structure for an experience."""
        now = time.time()
        await self.initialize()
        async with sqlite_transaction_async(self.db_path) as db:
            if expected_status is not None:
                async with db.execute(
                    """
                    SELECT 1 FROM experiences
                    WHERE experience_id = ? AND status = ?
                    """,
                    (experience_id, expected_status),
                ) as cursor:
                    if await cursor.fetchone() is None:
                        return False
            if not await _experience_row_is_active(
                db,
                experience_id=experience_id,
                require_derivable=True,
            ):
                raise ValueError(f"Experience sources are no longer active: {experience_id}")
            await _assert_draft_sources_are_active(
                db,
                chapters=chapters,
                possible_evidence=[],
                excluded_evidence=[],
            )
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
        return True

    async def list_experience_chapters(self, *, experience_id: str) -> list[dict[str, Any]]:
        """List the durable chapter structure for an experience."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if not await _experience_row_is_active(db, experience_id=experience_id):
                return []
            async with db.execute(
                """
                SELECT * FROM experience_chapters AS chapter
                WHERE chapter.experience_id = ?
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
            await db.execute("BEGIN IMMEDIATE")
            try:
                normalized_source_type = str(source_ref_type or "").strip()
                normalized_source_id = str(source_ref_id or "").strip()
                if normalized_source_type == "episode_group":
                    normalized_source_id = ",".join(
                        dict.fromkeys(
                            episode_id.strip()
                            for episode_id in normalized_source_id.split(",")
                            if episode_id.strip()
                        )
                    )
                    await _assert_episode_group_is_active(db, normalized_source_id)
                elif normalized_source_type in {"episode", "event", "summary"}:
                    await _assert_source_reference_is_active(
                        db,
                        ref_type=normalized_source_type,
                        ref_id=normalized_source_id,
                    )
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
                        normalized_source_type or None,
                        normalized_source_id or None,
                        None,
                        now,
                        now,
                        None,
                    ),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
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
            if (
                row is not None
                and str(row["status"] or "") in _DERIVABLE_SEED_STATUSES
                and not await _seed_row_is_active(db, row)
            ):
                row = None
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
        query += " ORDER BY created_at DESC, updated_at DESC"

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
            active_rows = [
                row
                for row in rows
                if str(row["status"] or "") not in _DERIVABLE_SEED_STATUSES
                or await _seed_row_is_active(db, row)
            ]
        page = active_rows[max(0, int(offset)) : max(0, int(offset)) + max(1, int(limit))]
        return [self._experience_seed_row_to_dict(row) for row in page]

    async def update_experience_seed(
        self,
        *,
        seed_id: str,
        expected_statuses: Iterable[str] | None = None,
        **fields: Any,
    ) -> bool:
        """Update mutable experience seed fields."""
        updates = {
            key: value for key, value in fields.items() if key in _ALLOWED_SEED_UPDATE_FIELDS
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
        where_clause = "seed_id = ?"
        values = list(updates.values()) + [seed_id]
        normalized_expected = tuple(
            dict.fromkeys(
                str(item).strip() for item in (expected_statuses or ()) if str(item).strip()
            )
        )
        if normalized_expected:
            placeholders = ", ".join("?" for _ in normalized_expected)
            where_clause += f" AND status IN ({placeholders})"
            values.extend(normalized_expected)

        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    "SELECT * FROM experience_seeds WHERE seed_id = ?",
                    (seed_id,),
                ) as current_cursor:
                    current = await current_cursor.fetchone()
                if current is None:
                    await db.rollback()
                    return False
                next_status = str(updates.get("status", current["status"]) or "")
                if next_status in _DERIVABLE_SEED_STATUSES and not await _seed_row_is_active(
                    db, current
                ):
                    raise ValueError(f"Experience seed is no longer active: {seed_id}")
                if "source_ref_type" in updates or "source_ref_id" in updates:
                    source_ref_type = str(
                        updates.get("source_ref_type", current["source_ref_type"]) or ""
                    ).strip()
                    source_ref_id = str(
                        updates.get("source_ref_id", current["source_ref_id"]) or ""
                    ).strip()
                    if source_ref_type == "episode_group":
                        await _assert_episode_group_is_active(db, source_ref_id)
                    elif source_ref_type in {"episode", "event", "summary"}:
                        await _assert_source_reference_is_active(
                            db,
                            ref_type=source_ref_type,
                            ref_id=source_ref_id,
                        )
                cursor = await db.execute(
                    f"UPDATE experience_seeds SET {set_clause} WHERE {where_clause}",
                    tuple(values),
                )
                await db.commit()
                return cursor.rowcount > 0
            except BaseException:
                await db.rollback()
                raise

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
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    "SELECT * FROM experience_seeds WHERE seed_id = ?",
                    (seed_id,),
                ) as cursor:
                    seed_row = await cursor.fetchone()
                if (
                    seed_row is None
                    or str(seed_row["status"] or "") not in _DERIVABLE_SEED_STATUSES
                    or not await _seed_row_is_active(db, seed_row)
                ):
                    raise ValueError(f"Experience seed no longer accepts evidence: {seed_id}")
                for item in evidence:
                    ref_type = str(_seed_evidence_value(item, "ref_type", "") or "").strip()
                    ref_id = str(_seed_evidence_value(item, "ref_id", "") or "").strip()
                    role = str(_seed_evidence_value(item, "role", "support") or "support").strip()
                    confidence = float(_seed_evidence_value(item, "confidence", 0.5) or 0.0)
                    reason = _seed_evidence_value(item, "reason")
                    if ref_type not in _SEED_EVIDENCE_REF_TYPES:
                        raise ValueError(
                            f"Unsupported experience seed evidence ref_type: {ref_type}"
                        )
                    if role not in _SEED_EVIDENCE_ROLES:
                        raise ValueError(f"Unsupported experience seed evidence role: {role}")
                    if not ref_id:
                        raise ValueError("Experience seed evidence ref_id is required")
                    if ref_type in {"episode", "event", "summary"}:
                        await _assert_source_reference_is_active(
                            db,
                            ref_type=ref_type,
                            ref_id=ref_id,
                        )
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
            except BaseException:
                await db.rollback()
                raise
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
                "SELECT * FROM experience_seeds WHERE seed_id = ?",
                (seed_id,),
            ) as seed_cursor:
                seed = await seed_cursor.fetchone()
            if seed is None or (
                str(seed["status"] or "") in _DERIVABLE_SEED_STATUSES
                and not await _seed_row_is_active(db, seed)
            ):
                return []
            async with db.execute(
                f"""
                SELECT * FROM experience_seed_evidence AS evidence
                WHERE evidence.seed_id = ?
                  AND {_active_seed_evidence_predicate("evidence")}
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
        validate_source_seed: bool = False,
    ) -> str:
        """Create a new experience row."""
        await self.initialize()
        now = time.time()
        row = dict(
            experience_id=experience_id,
            status=status,
            title=title,
            time_start=time_start,
            time_end=time_end,
            experience_type=experience_type,
            intent=intent,
            outcome=outcome,
            magi_interpretation=magi_interpretation,
            narrative_score=narrative_score,
            primary_entity_ids=primary_entity_ids,
            primary_place_ids=primary_place_ids,
            primary_topic_keys=primary_topic_keys,
            source_episode_count=source_episode_count,
            source_event_count=source_event_count,
            source_seed_id=source_seed_id,
            parent_experience_id=parent_experience_id,
            merged_into_experience_id=merged_into_experience_id,
            user_label=user_label,
            user_note=user_note,
            user_cover_asset_ref=user_cover_asset_ref,
            user_pinned=user_pinned,
            created_at=now,
            updated_at=now,
            last_recomputed_at=None,
        )
        await self._insert_experience_row(
            row,
            validate_source_seed=validate_source_seed,
        )
        return experience_id

    async def _insert_experience_row(
        self,
        row: dict[str, Any],
        *,
        validate_source_seed: bool,
    ) -> None:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                source_seed_id = str(row.get("source_seed_id") or "").strip()
                if source_seed_id:
                    if validate_source_seed:
                        await _assert_seed_is_promotable(db, seed_id=source_seed_id)
                    else:
                        await _assert_seed_reference_is_active(db, seed_id=source_seed_id)
                await db.execute(_EXPERIENCE_INSERT_SQL, _experience_insert_values(row))
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def get_experience(self, *, experience_id: str) -> dict[str, Any] | None:
        """Return one experience by ID."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT * FROM experiences AS experience
                WHERE experience.experience_id = ?
                  AND {_active_experience_predicate("experience")}
                """,
                (experience_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if (
                row is not None
                and str(row["status"] or "") in _DERIVABLE_EXPERIENCE_STATUSES
                and not await _experience_source_seed_is_active(db, row)
            ):
                row = None
        if row is None:
            return None
        experience = self._experience_row_to_dict(row)
        experience["chapters"] = await self.list_experience_chapters(experience_id=experience_id)
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
        query = f"""
            SELECT * FROM experiences AS experience
            WHERE {_active_experience_predicate("experience")}
        """
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
        query += " ORDER BY time_start DESC, time_end DESC"

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
            active_rows = [
                row
                for row in rows
                if str(row["status"] or "") not in _DERIVABLE_EXPERIENCE_STATUSES
                or await _experience_source_seed_is_active(db, row)
            ]
        page = active_rows[max(0, int(offset)) : max(0, int(offset)) + max(1, int(limit))]
        return [self._experience_row_to_dict(row) for row in page]

    async def update_experience(
        self,
        *,
        experience_id: str,
        expected_status: str | None = None,
        **fields: Any,
    ) -> bool:
        """Update mutable experience fields when its current status matches."""
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
        where_clause = "experience_id = ?"
        values = list(updates.values()) + [experience_id]
        if expected_status is not None:
            where_clause += " AND status = ?"
            values.append(str(expected_status))

        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                if "source_seed_id" in updates:
                    source_seed_id = str(updates["source_seed_id"] or "").strip()
                    if source_seed_id:
                        await _assert_seed_reference_is_active(db, seed_id=source_seed_id)
                cursor = await db.execute(
                    f"UPDATE experiences SET {set_clause} WHERE {where_clause}",
                    tuple(values),
                )
                await db.commit()
                return cursor.rowcount > 0
            except BaseException:
                await db.rollback()
                raise

    async def add_experience_members(
        self,
        *,
        experience_id: str,
        members: Iterable[ExperienceMemberWrite | dict[str, Any]],
        expected_status: str | None = None,
    ) -> int:
        """Add source episode/event memberships. Returns newly inserted count."""
        await self.initialize()
        normalized_members = list(members)
        now = time.time()
        added = 0
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                if expected_status is not None:
                    async with db.execute(
                        "SELECT 1 FROM experiences WHERE experience_id = ? AND status = ?",
                        (experience_id, expected_status),
                    ) as cursor:
                        if await cursor.fetchone() is None:
                            await db.rollback()
                            return 0
                if not await _experience_row_is_active(
                    db,
                    experience_id=experience_id,
                    require_derivable=True,
                ):
                    raise ValueError(f"Experience sources are no longer active: {experience_id}")
                await _assert_member_sources_are_active(db, normalized_members)
                for index, member in enumerate(normalized_members):
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
                        (
                            experience_id,
                            member_type,
                            member_id,
                            role,
                            confidence,
                            now + index * 0.000001,
                        ),
                    )
                    added += int(cursor.rowcount > 0)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return added

    async def replace_experience_members(
        self,
        *,
        experience_id: str,
        members: Iterable[ExperienceMemberWrite | dict[str, Any]],
        expected_status: str | None = None,
    ) -> int:
        """Replace all source memberships in one transaction."""
        await self.initialize()
        values = _experience_member_insert_values(
            members,
            experience_id=experience_id,
            added_at=time.time(),
        )
        async with sqlite_transaction_async(self.db_path) as db:
            if expected_status is not None:
                async with db.execute(
                    "SELECT 1 FROM experiences WHERE experience_id = ? AND status = ?",
                    (experience_id, expected_status),
                ) as cursor:
                    if await cursor.fetchone() is None:
                        return 0
            if not await _experience_row_is_active(
                db,
                experience_id=experience_id,
                require_derivable=True,
            ):
                raise ValueError(f"Experience sources are no longer active: {experience_id}")
            await _assert_member_sources_are_active(
                db,
                [
                    {
                        "member_type": value[1],
                        "member_id": value[2],
                    }
                    for value in values
                ],
            )
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
            if not await _experience_row_is_active(db, experience_id=experience_id):
                return []
            async with db.execute(
                f"""
                SELECT * FROM experience_members AS member
                WHERE member.experience_id = ?
                  AND {_active_member_predicate("member")}
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
            if not await _experience_row_is_active(db, experience_id=experience_id):
                return 0
            async with db.execute(
                f"""
                SELECT COUNT(*) FROM experience_members AS member
                WHERE member.experience_id = ? AND member.role != 'excluded'
                  AND {_active_member_predicate("member")}
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
            await db.execute("BEGIN IMMEDIATE")
            try:
                if not await _experience_row_is_active(
                    db,
                    experience_id=experience_id,
                    require_derivable=True,
                ):
                    await db.rollback()
                    return {"source_episode_count": 0, "source_event_count": 0}
                active_episode_member = _active_member_predicate("member")
                async with db.execute(
                    f"""
                    SELECT COUNT(DISTINCT member.member_id)
                    FROM experience_members AS member
                    WHERE member.experience_id = ?
                      AND member.member_type = 'episode'
                      AND member.role != 'excluded'
                      AND {active_episode_member}
                    """,
                    (experience_id,),
                ) as cursor:
                    episode_row = await cursor.fetchone()
                active_episode_ref = _active_source_reference_predicate(
                    "em.member_type",
                    "em.member_id",
                )
                active_event_ref = _active_event_reference_predicate("em.member_id")
                async with db.execute(
                    f"""
                    SELECT COUNT(DISTINCT source_event_id)
                    FROM (
                        SELECT ee.event_id AS source_event_id
                        FROM experience_members em
                        JOIN episode_events ee ON ee.episode_id = em.member_id
                        WHERE em.experience_id = ?
                          AND em.member_type = 'episode'
                          AND em.role != 'excluded'
                          AND {active_episode_ref}
                          AND {_active_event_reference_predicate("ee.event_id")}
                        UNION
                        SELECT em.member_id AS source_event_id
                        FROM experience_members em
                        WHERE em.experience_id = ?
                          AND em.member_type = 'event'
                          AND em.role != 'excluded'
                          AND {active_event_ref}
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
            except BaseException:
                await db.rollback()
                raise
        return {
            "source_episode_count": source_episode_count,
            "source_event_count": source_event_count,
        }


__all__ = ["L2ExperienceStoreMixin"]
