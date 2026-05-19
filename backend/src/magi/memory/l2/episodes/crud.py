"""CRUD helpers for L2 episode persistence."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .codec import L2EpisodeStoreBaseMixin


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
        privacy_scope: str = "private",
        slice_narrative: Optional[str] = None,
        slice_sensory_detail: Optional[str] = None,
        magi_standout: bool = False,
        standout_score: float = 0.0,
        standout_reason: Optional[str] = None,
        representative_asset_ref: Optional[str] = None,
    ) -> str:
        """Create a new episode record."""
        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO episodes(
                    episode_id, episode_type, status, time_start, time_end,
                    parent_episode_id, label, summary, dominant_mode,
                    primary_entity_ids, primary_place_ids, primary_topic_keys,
                    continuity_signals, formation_method, confidence,
                    source_event_count, privacy_scope,
                    slice_narrative, slice_sensory_detail, magi_standout,
                    standout_score, standout_reason, representative_asset_ref,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    episode_type,
                    status,
                    time_start,
                    time_end,
                    parent_episode_id,
                    label,
                    summary,
                    dominant_mode,
                    json.dumps(primary_entity_ids or [], ensure_ascii=False),
                    json.dumps(primary_place_ids or [], ensure_ascii=False),
                    json.dumps(primary_topic_keys or [], ensure_ascii=False),
                    json.dumps(continuity_signals or [], ensure_ascii=False),
                    formation_method,
                    confidence,
                    source_event_count,
                    privacy_scope,
                    slice_narrative,
                    slice_sensory_detail,
                    1 if magi_standout else 0,
                    standout_score,
                    standout_reason,
                    representative_asset_ref,
                    now,
                    now,
                ),
            )
            await db.commit()
        return episode_id

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
        **fields: Any,
    ) -> bool:
        """Update mutable fields of an episode. Returns True if found."""
        allowed = {
            "status", "time_start", "time_end", "label", "summary",
            "dominant_mode", "primary_entity_ids", "primary_place_ids",
            "primary_topic_keys", "continuity_signals", "confidence",
            "source_event_count", "parent_episode_id", "user_label",
            "user_note", "user_pinned", "embedding_status",
            "embedding_profile_id", "last_embedded_at", "last_recomputed_at",
            "privacy_scope",
            # Immersive timeline fields (Plan 1)
            "slice_narrative", "slice_sensory_detail", "magi_standout",
            "standout_score", "standout_reason", "representative_asset_ref",
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
        values = list(updates.values()) + [episode_id]

        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE episodes SET {set_clause} WHERE episode_id = ?",
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


__all__ = ["L2EpisodeCrudMixin"]
