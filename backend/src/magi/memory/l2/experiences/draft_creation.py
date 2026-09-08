"""Create an active L2 experience from a user-approved draft."""

from __future__ import annotations

import math
import time
import uuid
from typing import Any

from ....core.sqlite import sqlite_transaction_async
from .codec import L2ExperienceStoreBaseMixin
from .store import (
    _EXPERIENCE_INSERT_SQL,
    _assert_draft_sources_are_active,
    _experience_insert_values,
    _experience_member_insert_values,
    _experience_row_is_active,
    _read_experience_counts,
    _write_experience_chapters,
)


def _ordered_unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _experience_id_for_draft(draft_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"magi://experience-drafts/{draft_id}"))


async def create_experience_from_draft(
    store: L2ExperienceStoreBaseMixin, *, draft_id: str,
    expected_updated_at: float | None = None,
) -> str:
    """Atomically promote the approved snapshot and retain its retry receipt."""
    await store.initialize()
    async with sqlite_transaction_async(store.db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        rows = await db.execute_fetchall("SELECT * FROM experience_drafts WHERE draft_id = ?", (draft_id,))
        if not rows:
            raise ValueError(f"Experience draft not found: {draft_id}")
        draft = store._experience_draft_row_to_dict(rows[0])
        created_id = str(draft.get("created_experience_id") or "").strip()
        if draft["status"] == "completed" and created_id:
            active_rows = await db.execute_fetchall("SELECT 1 FROM experiences WHERE experience_id = ? AND status = 'active'", (created_id,))
            if not active_rows or not await _experience_row_is_active(db, experience_id=created_id, require_derivable=True):
                raise ValueError(f"Draft experience is no longer active: {created_id}")
            return created_id
        if draft["status"] != "editing":
            raise ValueError(f"Experience draft is not editable: {draft_id}")
        if expected_updated_at is not None and draft["updated_at"] != expected_updated_at:
            raise ValueError("Experience draft changed; reload its current snapshot")
        chapters = list(draft.get("chapters") or [])
        episode_ids = _ordered_unique([ref for chapter in chapters for ref in chapter.get("episode_ids") or []])
        event_ids = _ordered_unique([ref for chapter in chapters for ref in chapter.get("event_ids") or []])
        if not episode_ids and not event_ids:
            raise ValueError("Experience draft has no selected evidence")
        await _assert_draft_sources_are_active(db, chapters=chapters, possible_evidence=[], excluded_evidence=[])
        experience_id = _experience_id_for_draft(draft_id)
        now = max(time.time(), math.nextafter(draft["updated_at"], math.inf))
        row = dict(
            experience_id=experience_id, status="active", title=draft["title"],
            time_start=draft["time_start"], time_end=draft["time_end"],
            intent=draft["title"], magi_interpretation=draft["one_sentence_review"],
            user_cover_asset_ref=draft.get("user_cover_asset_ref"), narrative_score=0.0,
            source_episode_count=len(episode_ids), source_event_count=len(event_ids),
            created_at=now, updated_at=now, last_recomputed_at=now,
        )
        await db.execute(_EXPERIENCE_INSERT_SQL, _experience_insert_values(row))
        members = [
            {"member_type": kind, "member_id": ref, "role": "core", "confidence": 1.0}
            for kind, refs in (("episode", episode_ids), ("event", event_ids)) for ref in refs
        ]
        await db.executemany(
            """INSERT INTO experience_members(
                experience_id, member_type, member_id, role, confidence, added_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            _experience_member_insert_values(members, experience_id=experience_id, added_at=now),
        )
        await _write_experience_chapters(db, experience_id=experience_id, chapters=chapters, now=now)
        episode_count, event_count = await _read_experience_counts(db, experience_id)
        await db.execute(
            "UPDATE experiences SET source_episode_count = ?, source_event_count = ? WHERE experience_id = ?",
            (episode_count, event_count, experience_id),
        )
        await db.execute(
            """UPDATE experience_drafts SET status = 'completed',
                created_experience_id = ?, updated_at = ? WHERE draft_id = ?""",
            (experience_id, now, draft_id),
        )
    return experience_id


__all__ = ["create_experience_from_draft"]
