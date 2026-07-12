"""Create an active L2 experience from a user-approved draft."""

from __future__ import annotations

import uuid
from typing import Any


def _ordered_unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


async def create_experience_from_draft(store: Any, *, draft_id: str) -> str:
    """Promote one editable draft without rerunning inference."""
    draft = await store.get_experience_draft(draft_id=draft_id)
    if draft is None:
        raise ValueError(f"Experience draft not found: {draft_id}")
    created_experience_id = str(draft.get("created_experience_id") or "").strip()
    if draft.get("status") == "completed" and created_experience_id:
        return created_experience_id
    if draft["status"] != "editing":
        raise ValueError(f"Experience draft is not editable: {draft_id}")
    chapters = list(draft.get("chapters") or [])
    episode_ids = _ordered_unique([
        episode_id
        for chapter in chapters
        for episode_id in (chapter.get("episode_ids") or [])
    ])
    event_ids = _ordered_unique([
        event_id
        for chapter in chapters
        for event_id in (chapter.get("event_ids") or [])
    ])
    if not episode_ids and not event_ids:
        raise ValueError("Experience draft has no selected evidence")

    experience_id = str(uuid.uuid4())
    await store.create_experience(
        experience_id=experience_id,
        status="active",
        title=str(draft["title"]),
        time_start=float(draft["time_start"]),
        time_end=float(draft["time_end"]),
        intent=str(draft["title"]),
        magi_interpretation=str(draft["one_sentence_review"]),
        source_episode_count=len(episode_ids),
        source_event_count=len(event_ids),
    )
    members = [
        {
            "member_type": "episode",
            "member_id": episode_id,
            "role": "core",
            "confidence": 1.0,
        }
        for episode_id in episode_ids
    ]
    members.extend(
        {
            "member_type": "event",
            "member_id": event_id,
            "role": "core",
            "confidence": 1.0,
        }
        for event_id in event_ids
    )
    await store.add_experience_members(experience_id=experience_id, members=members)
    await store.replace_experience_chapters(
        experience_id=experience_id,
        chapters=chapters,
    )
    await store.recompute_experience_counts(experience_id=experience_id)
    await store.update_experience_draft(
        draft_id=draft_id,
        status="completed",
        created_experience_id=experience_id,
    )
    return experience_id


__all__ = ["create_experience_from_draft"]
