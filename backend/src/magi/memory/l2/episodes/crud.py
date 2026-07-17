"""CRUD helpers for L2 episode persistence."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...source_event_governance import matching_time_range_forget_barriers
from .codec import L2EpisodeStoreBaseMixin


class ForgottenEpisodeTimeRangeError(RuntimeError):
    """Raised when an episode would recreate a forgotten occurrence range."""


_EPISODE_LIST_INSERT_COLUMNS = {
    "primary_entity_ids",
    "primary_place_ids",
    "primary_topic_keys",
    "continuity_signals",
}
_EPISODE_INSERT_COLUMNS = (
    "episode_id",
    "episode_type",
    "status",
    "time_start",
    "time_end",
    "parent_episode_id",
    "label",
    "summary",
    "dominant_mode",
    "primary_entity_ids",
    "primary_place_ids",
    "primary_topic_keys",
    "continuity_signals",
    "formation_method",
    "confidence",
    "source_event_count",
    "slice_narrative",
    "slice_sensory_detail",
    "magi_standout",
    "standout_score",
    "standout_reason",
    "representative_asset_ref",
    "created_at",
    "updated_at",
)
_EPISODE_INSERT_SQL = f"""
    INSERT INTO episodes({", ".join(_EPISODE_INSERT_COLUMNS)})
    VALUES ({", ".join("?" for _ in _EPISODE_INSERT_COLUMNS)})
"""


def _merge_json_lists(*raw_values: Any) -> list[str]:
    """Merge stored JSON-list columns while preserving first-seen order."""
    merged: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        try:
            values = json.loads(raw_value or "[]") if isinstance(raw_value, str) else raw_value
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        if not isinstance(values, list):
            continue
        for value in values:
            text = str(value).strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def _episode_json_list(values: list[str] | None) -> str:
    return json.dumps(values or [], ensure_ascii=False)


def _episode_insert_values(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _episode_insert_value(column, row.get(column)) for column in _EPISODE_INSERT_COLUMNS
    )


def _episode_insert_value(column: str, value: Any) -> Any:
    if column in _EPISODE_LIST_INSERT_COLUMNS:
        return _episode_json_list(value)
    if column == "magi_standout":
        return 1 if value else 0
    return value


@dataclass(frozen=True)
class _EpisodeChildSpec:
    episode_id: str
    event_ids: List[str]
    time_start: float
    time_end: float

    @property
    def source_event_count(self) -> int:
        return len(self.event_ids)


@dataclass(frozen=True)
class _EpisodeSplitRequest:
    source_episode_id: str
    left: _EpisodeChildSpec
    right: _EpisodeChildSpec

    def is_valid(self) -> bool:
        if not self.left.event_ids or not self.right.event_ids:
            return False
        if self.source_episode_id in {self.left.episode_id, self.right.episode_id}:
            return False
        return self.left.episode_id != self.right.episode_id

    @property
    def children(self) -> tuple[_EpisodeChildSpec, _EpisodeChildSpec]:
        return (self.left, self.right)


async def _fetch_episode_row(db: aiosqlite.Connection, *, episode_id: str) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT * FROM episodes WHERE episode_id = ?",
        (episode_id,),
    ) as cursor:
        return await cursor.fetchone()


async def _fetch_merge_episode_rows(
    db: aiosqlite.Connection,
    *,
    survivor_id: str,
    absorbed_id: str,
) -> tuple[aiosqlite.Row | None, aiosqlite.Row | None]:
    async with db.execute(
        "SELECT * FROM episodes WHERE episode_id IN (?, ?)",
        (survivor_id, absorbed_id),
    ) as cursor:
        rows = await cursor.fetchall()
    episodes = {str(row["episode_id"]): row for row in rows}
    return episodes.get(survivor_id), episodes.get(absorbed_id)


async def _move_absorbed_episode_memberships(
    db: aiosqlite.Connection,
    *,
    survivor_id: str,
    absorbed_id: str,
    now: float,
) -> None:
    async with db.execute(
        "SELECT event_id FROM episode_events WHERE episode_id = ? ORDER BY added_at ASC",
        (absorbed_id,),
    ) as cursor:
        absorbed_event_rows = await cursor.fetchall()
    absorbed_event_ids = [
        str(row["event_id"]) for row in absorbed_event_rows if row and row["event_id"]
    ]
    for event_id in absorbed_event_ids:
        await db.execute(
            """
            INSERT OR IGNORE INTO episode_events(
                episode_id, event_id, membership_role, membership_confidence, added_at
            ) VALUES (?, ?, 'member', 0.5, ?)
            """,
            (survivor_id, event_id, now),
        )
    await db.execute(
        "DELETE FROM episode_events WHERE episode_id = ?",
        (absorbed_id,),
    )


async def _count_episode_memberships(db: aiosqlite.Connection, *, episode_id: str) -> int:
    async with db.execute(
        "SELECT COUNT(*) FROM episode_events WHERE episode_id = ?",
        (episode_id,),
    ) as cursor:
        count_row = await cursor.fetchone()
    return int(count_row[0]) if count_row else 0


async def _update_merged_survivor_episode(
    db: aiosqlite.Connection,
    *,
    survivor_id: str,
    survivor: aiosqlite.Row,
    absorbed: aiosqlite.Row,
    source_event_count: int,
    now: float,
) -> None:
    primary_entity_ids = _merge_json_lists(
        survivor["primary_entity_ids"], absorbed["primary_entity_ids"]
    )
    primary_place_ids = _merge_json_lists(
        survivor["primary_place_ids"], absorbed["primary_place_ids"]
    )
    primary_topic_keys = _merge_json_lists(
        survivor["primary_topic_keys"], absorbed["primary_topic_keys"]
    )
    continuity_signals = _merge_json_lists(
        survivor["continuity_signals"], absorbed["continuity_signals"]
    )
    await db.execute(
        """
        UPDATE episodes
        SET time_start = ?, time_end = ?,
            primary_entity_ids = ?, primary_place_ids = ?,
            primary_topic_keys = ?, continuity_signals = ?,
            source_event_count = ?, updated_at = ?
        WHERE episode_id = ?
        """,
        (
            min(float(survivor["time_start"]), float(absorbed["time_start"])),
            max(float(survivor["time_end"]), float(absorbed["time_end"])),
            json.dumps(primary_entity_ids, ensure_ascii=False),
            json.dumps(primary_place_ids, ensure_ascii=False),
            json.dumps(primary_topic_keys, ensure_ascii=False),
            json.dumps(continuity_signals, ensure_ascii=False),
            source_event_count,
            now,
            survivor_id,
        ),
    )


async def _mark_episode_merged(
    db: aiosqlite.Connection,
    *,
    absorbed_id: str,
    survivor_id: str,
    now: float,
) -> None:
    await db.execute(
        """
        UPDATE episodes
        SET status = 'merged',
            parent_episode_id = ?,
            source_event_count = 0,
            updated_at = ?
        WHERE episode_id = ?
        """,
        (survivor_id, now, absorbed_id),
    )


async def _insert_split_child_episodes(
    db: aiosqlite.Connection,
    split_request: _EpisodeSplitRequest,
    source: aiosqlite.Row,
    *,
    now: float,
) -> None:
    for child in split_request.children:
        await db.execute(
            """
            INSERT INTO episodes(
                episode_id, episode_type, status, time_start, time_end,
                parent_episode_id, label, summary, dominant_mode,
                primary_entity_ids, primary_place_ids, primary_topic_keys,
                continuity_signals, formation_method, confidence,
                source_event_count,
                slice_narrative, slice_sensory_detail, magi_standout,
                standout_score, standout_reason, representative_asset_ref,
                created_at, updated_at
            ) VALUES (?, ?, 'active', ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, 'user_split', ?, ?, NULL, NULL, 0, 0.0, NULL, NULL, ?, ?)
            """,
            (
                child.episode_id,
                str(source["episode_type"]),
                child.time_start,
                child.time_end,
                split_request.source_episode_id,
                source["dominant_mode"],
                source["primary_entity_ids"],
                source["primary_place_ids"],
                source["primary_topic_keys"],
                source["continuity_signals"],
                float(source["confidence"]),
                child.source_event_count,
                now,
                now,
            ),
        )


async def _load_episode_memberships(
    db: aiosqlite.Connection,
    episode_id: str,
) -> dict[str, aiosqlite.Row]:
    async with db.execute(
        "SELECT * FROM episode_events WHERE episode_id = ?",
        (episode_id,),
    ) as cursor:
        membership_rows = await cursor.fetchall()
    return {str(row["event_id"]): row for row in membership_rows}


async def _insert_split_child_memberships(
    db: aiosqlite.Connection,
    split_request: _EpisodeSplitRequest,
    memberships: dict[str, aiosqlite.Row],
    *,
    now: float,
) -> None:
    for child in split_request.children:
        for event_id in child.event_ids:
            membership = memberships.get(str(event_id))
            await _insert_split_child_membership(
                db,
                child_episode_id=child.episode_id,
                event_id=str(event_id),
                membership=membership,
                now=now,
            )


async def _insert_split_child_membership(
    db: aiosqlite.Connection,
    *,
    child_episode_id: str,
    event_id: str,
    membership: aiosqlite.Row | None,
    now: float,
) -> None:
    await db.execute(
        """
        INSERT OR IGNORE INTO episode_events(
            episode_id, event_id, membership_role, membership_confidence, added_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            child_episode_id,
            event_id,
            str(membership["membership_role"]) if membership else "member",
            float(membership["membership_confidence"]) if membership else 0.5,
            now,
        ),
    )


async def _invalidate_split_source_episode(
    db: aiosqlite.Connection,
    source_episode_id: str,
    *,
    now: float,
) -> None:
    await db.execute(
        "DELETE FROM episode_events WHERE episode_id = ?",
        (source_episode_id,),
    )
    await db.execute(
        """
        UPDATE episodes
        SET status = 'invalidated',
            source_event_count = 0,
            updated_at = ?
        WHERE episode_id = ?
        """,
        (now, source_episode_id),
    )


async def _fetch_split_children(
    db: aiosqlite.Connection,
    split_request: _EpisodeSplitRequest,
) -> tuple[aiosqlite.Row | None, aiosqlite.Row | None]:
    left_after = await _fetch_episode_row(db, episode_id=split_request.left.episode_id)
    right_after = await _fetch_episode_row(db, episode_id=split_request.right.episode_id)
    return left_after, right_after


class L2EpisodeCrudMixin(L2EpisodeStoreBaseMixin):
    """Create, update, fetch, list, and count L2 episodes."""

    async def create_episode(
        self,
        *,
        episode_id: str,
        episode_type: str = "activity",
        status: str = "candidate",
        time_start: float,
        time_end: float,
        parent_episode_id: Optional[str] = None,
        label: Optional[str] = None,
        summary: Optional[str] = None,
        dominant_mode: Optional[str] = None,
        primary_entity_ids: Optional[List[str]] = None,
        primary_place_ids: Optional[List[str]] = None,
        primary_topic_keys: Optional[List[str]] = None,
        continuity_signals: Optional[List[str]] = None,
        formation_method: str = "time_gap_cluster",
        confidence: float = 0.5,
        source_event_count: int = 0,
        slice_narrative: Optional[str] = None,
        slice_sensory_detail: Optional[str] = None,
        magi_standout: bool = False,
        standout_score: float = 0.0,
        standout_reason: Optional[str] = None,
        representative_asset_ref: Optional[str] = None,
    ) -> str:
        """Create a new episode record."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            barriers = await matching_time_range_forget_barriers(
                db,
                observed_from=float(time_start),
                observed_to=float(time_end),
            )
        if barriers:
            raise ForgottenEpisodeTimeRangeError(
                "Episode occurrence overlaps a forgotten time range"
            )
        now = time.time()
        row = dict(
            episode_id=episode_id,
            episode_type=episode_type,
            status=status,
            time_start=time_start,
            time_end=time_end,
            parent_episode_id=parent_episode_id,
            label=label,
            summary=summary,
            dominant_mode=dominant_mode,
            primary_entity_ids=primary_entity_ids,
            primary_place_ids=primary_place_ids,
            primary_topic_keys=primary_topic_keys,
            continuity_signals=continuity_signals,
            formation_method=formation_method,
            confidence=confidence,
            source_event_count=source_event_count,
            slice_narrative=slice_narrative,
            slice_sensory_detail=slice_sensory_detail,
            magi_standout=magi_standout,
            standout_score=standout_score,
            standout_reason=standout_reason,
            representative_asset_ref=representative_asset_ref,
            created_at=now,
            updated_at=now,
        )
        await self._insert_episode_row(row)
        return episode_id

    async def _insert_episode_row(self, row: dict[str, Any]) -> None:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(_EPISODE_INSERT_SQL, _episode_insert_values(row))
            await db.commit()

    async def get_episode(self, *, episode_id: str) -> Optional[Dict[str, Any]]:
        """Get a single episode by ID."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return self._episode_row_to_dict(row)

    async def update_episode(
        self,
        *,
        episode_id: str,
        expected_status: str | None = None,
        **fields: Any,
    ) -> bool:
        """Update mutable fields of an episode when its current status matches."""
        allowed = {
            "status",
            "time_start",
            "time_end",
            "label",
            "summary",
            "dominant_mode",
            "primary_entity_ids",
            "primary_place_ids",
            "primary_topic_keys",
            "continuity_signals",
            "confidence",
            "source_event_count",
            "parent_episode_id",
            "user_label",
            "user_note",
            "user_pinned",
            "embedding_status",
            "embedding_profile_id",
            "last_embedded_at",
            "last_recomputed_at",
            # Immersive timeline fields (Plan 1)
            "slice_narrative",
            "slice_sensory_detail",
            "magi_standout",
            "standout_score",
            "standout_reason",
            "representative_asset_ref",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return False

        for list_field in (
            "primary_entity_ids",
            "primary_place_ids",
            "primary_topic_keys",
            "continuity_signals",
        ):
            if list_field in updates and isinstance(updates[list_field], list):
                updates[list_field] = json.dumps(updates[list_field], ensure_ascii=False)

        if "magi_standout" in updates:
            updates["magi_standout"] = 1 if updates["magi_standout"] else 0

        updates["updated_at"] = time.time()
        set_clause = ", ".join(f"{key} = ?" for key in updates)
        where_clause = "episode_id = ?"
        values = list(updates.values()) + [episode_id]
        if expected_status is not None:
            where_clause += " AND status = ?"
            values.append(str(expected_status))

        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE episodes SET {set_clause} WHERE {where_clause}",
                tuple(values),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def list_episodes(
        self,
        *,
        status: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        episode_type: Optional[str] = None,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None,
        parent_episode_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List episodes with optional filters."""
        await self.initialize()
        query = "SELECT * FROM episodes WHERE 1=1"
        args: list[Any] = []
        if status:
            query += " AND status = ?"
            args.append(status)
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            args.extend(statuses)
        if episode_type:
            query += " AND episode_type = ?"
            args.append(episode_type)
        if time_start is not None:
            query += " AND time_end >= ?"
            args.append(time_start)
        if time_end is not None:
            query += " AND time_start <= ?"
            args.append(time_end)
        if parent_episode_id is not None:
            query += " AND parent_episode_id = ?"
            args.append(parent_episode_id)
        query += " ORDER BY time_start DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._episode_row_to_dict(row) for row in rows]

    async def count_episodes(
        self,
        *,
        status: Optional[str] = None,
        statuses: Optional[List[str]] = None,
    ) -> int:
        """Count episodes with optional status filter."""
        await self.initialize()
        query = "SELECT COUNT(*) FROM episodes WHERE 1=1"
        args: list[Any] = []
        if status:
            query += " AND status = ?"
            args.append(status)
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            args.extend(statuses)
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(query, tuple(args)) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def merge_episodes(
        self,
        *,
        survivor_id: str,
        absorbed_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Irreversibly merge one episode into another.

        Event memberships are moved onto the survivor and removed from the
        absorbed episode. The absorbed row remains as a terminal ``merged``
        marker with ``parent_episode_id`` pointing at the survivor.
        """
        if survivor_id == absorbed_id:
            return None

        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                survivor, absorbed = await _fetch_merge_episode_rows(
                    db,
                    survivor_id=survivor_id,
                    absorbed_id=absorbed_id,
                )
                if survivor is None or absorbed is None:
                    await db.rollback()
                    return None
                if str(survivor["status"]) != "active" or str(absorbed["status"]) != "active":
                    await db.rollback()
                    return None

                await _move_absorbed_episode_memberships(
                    db,
                    survivor_id=survivor_id,
                    absorbed_id=absorbed_id,
                    now=now,
                )
                source_event_count = await _count_episode_memberships(
                    db,
                    episode_id=survivor_id,
                )
                await _update_merged_survivor_episode(
                    db,
                    survivor_id=survivor_id,
                    survivor=survivor,
                    absorbed=absorbed,
                    source_event_count=source_event_count,
                    now=now,
                )
                await _mark_episode_merged(
                    db,
                    absorbed_id=absorbed_id,
                    survivor_id=survivor_id,
                    now=now,
                )
                survivor_after = await _fetch_episode_row(db, episode_id=survivor_id)
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        return self._episode_row_to_dict(survivor_after) if survivor_after else None

    async def split_episode(
        self,
        *,
        source_episode_id: str,
        left_episode_id: str,
        right_episode_id: str,
        left_event_ids: List[str],
        right_event_ids: List[str],
        left_time_start: float,
        left_time_end: float,
        right_time_start: float,
        right_time_end: float,
    ) -> Optional[Dict[str, Any]]:
        """Split one episode into two active child episodes."""
        split_request = _EpisodeSplitRequest(
            source_episode_id=source_episode_id,
            left=_EpisodeChildSpec(
                episode_id=left_episode_id,
                event_ids=left_event_ids,
                time_start=float(left_time_start),
                time_end=float(left_time_end),
            ),
            right=_EpisodeChildSpec(
                episode_id=right_episode_id,
                event_ids=right_event_ids,
                time_start=float(right_time_start),
                time_end=float(right_time_end),
            ),
        )
        if not split_request.is_valid():
            return None

        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                source = await _fetch_episode_row(db, episode_id=source_episode_id)
                if source is None or str(source["status"]) != "active":
                    await db.rollback()
                    return None

                await _insert_split_child_episodes(db, split_request, source, now=now)
                memberships = await _load_episode_memberships(db, source_episode_id)
                await _insert_split_child_memberships(db, split_request, memberships, now=now)
                await _invalidate_split_source_episode(db, source_episode_id, now=now)
                left_after, right_after = await _fetch_split_children(db, split_request)
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        if left_after is None or right_after is None:
            return None
        return {
            "left": self._episode_row_to_dict(left_after),
            "right": self._episode_row_to_dict(right_after),
        }

    async def find_recent_candidate_episode(
        self,
        *,
        episode_type: str = "activity",
        max_gap: float,
        before_time: float,
        entity_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Find the most recent candidate episode that ends within max_gap of before_time."""
        await self.initialize()
        cutoff = before_time - max_gap
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM episodes
                WHERE status = 'candidate'
                  AND episode_type = ?
                  AND time_end >= ?
                  AND time_end <= ?
                ORDER BY time_end DESC
                LIMIT 5
                """,
                (episode_type, cutoff, before_time),
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return None

        if entity_ids:
            target_set = set(entity_ids)
            for row in rows:
                episode = self._episode_row_to_dict(row)
                episode_entities = set(episode.get("primary_entity_ids") or [])
                if episode_entities & target_set:
                    return episode

        return self._episode_row_to_dict(rows[0])

    async def list_standout_episodes(
        self,
        *,
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List episodes that are either magi-curated or user-pinned.

        ``period_start`` is inclusive, ``period_end`` is exclusive (half-open interval).
        This matches the canonical [start, end) convention so callers can pass the
        first instant of the next period as the upper bound without double-counting.
        If both are None, returns the most-recent ``limit`` standouts regardless of date.
        """
        await self.initialize()
        # Terminal-state episodes (merged into a survivor / invalidated) must never
        # leak into the standout sidebar even if their magi_standout flag is still 1
        # — the merge/invalidate transitions only flip status, not the flag (#16).
        clauses: list[str] = [
            "(magi_standout = 1 OR user_pinned = 1)",
            "status NOT IN ('merged', 'invalidated')",
        ]
        params: list[Any] = []
        if period_start is not None:
            clauses.append("time_start >= ?")
            params.append(period_start)
        if period_end is not None:
            clauses.append("time_start < ?")
            params.append(period_end)
        params.append(int(max(1, limit)))
        sql = (
            "SELECT * FROM episodes WHERE "
            + " AND ".join(clauses)
            + " ORDER BY time_start DESC LIMIT ?"
        )
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
        return [self._episode_row_to_dict(r) for r in rows]


__all__ = ["L2EpisodeCrudMixin"]
