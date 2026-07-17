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


def _experience_id_for_draft(draft_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"magi://experience-drafts/{draft_id}"))


async def create_experience_from_draft(store: Any, *, draft_id: str) -> str:
    """Promote one editable draft without rerunning inference."""
    draft = await store.get_experience_draft(draft_id=draft_id)
    if draft is None:
        raise ValueError(f"Experience draft not found: {draft_id}")
    created_experience_id = str(draft.get("created_experience_id") or "").strip()
    if draft.get("status") == "completed" and created_experience_id:
        experience = await store.get_experience(experience_id=created_experience_id)
        if experience is None or str(experience.get("status") or "") != "active":
            raise ValueError(f"Draft experience is no longer active: {created_experience_id}")
        return created_experience_id
    if draft["status"] != "editing":
        raise ValueError(f"Experience draft is not editable: {draft_id}")
    chapters = list(draft.get("chapters") or [])
    episode_ids = _ordered_unique(
        [episode_id for chapter in chapters for episode_id in (chapter.get("episode_ids") or [])]
    )
    event_ids = _ordered_unique(
        [event_id for chapter in chapters for event_id in (chapter.get("event_ids") or [])]
    )
    if not episode_ids and not event_ids:
        raise ValueError("Experience draft has no selected evidence")
    await store.validate_experience_sources(
        episode_ids=episode_ids,
        event_ids=event_ids,
    )

    experience_id = _experience_id_for_draft(draft_id)
    experience = await store.get_experience(experience_id=experience_id)
    if experience is None:
        await store.create_experience(
            experience_id=experience_id,
            status="active",
            title=str(draft["title"]),
            time_start=float(draft["time_start"]),
            time_end=float(draft["time_end"]),
            intent=str(draft["title"]),
            magi_interpretation=str(draft["one_sentence_review"]),
            user_cover_asset_ref=draft.get("user_cover_asset_ref"),
            source_episode_count=len(episode_ids),
            source_event_count=len(event_ids),
        )
    else:
        if str(experience.get("status") or "") != "active":
            raise ValueError(f"Draft experience is no longer active: {experience_id}")
        updated = await store.update_experience(
            experience_id=experience_id,
            expected_status="active",
            title=str(draft["title"]),
            time_start=float(draft["time_start"]),
            time_end=float(draft["time_end"]),
            intent=str(draft["title"]),
            magi_interpretation=str(draft["one_sentence_review"]),
            user_cover_asset_ref=draft.get("user_cover_asset_ref"),
        )
        if not updated:
            raise ValueError(f"Draft experience changed during creation: {experience_id}")
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
    try:
        replaced = await store.replace_experience_members(
            experience_id=experience_id,
            members=members,
            expected_status="active",
        )
    except ValueError:
        await store.update_experience(
            experience_id=experience_id,
            expected_status="active",
            status="invalidated",
        )
        raise
    if replaced != len(members):
        await store.update_experience(
            experience_id=experience_id,
            expected_status="active",
            status="invalidated",
        )
        raise ValueError("Draft evidence changed during creation")
    try:
        chapters_replaced = await store.replace_experience_chapters(
            experience_id=experience_id,
            chapters=chapters,
            expected_status="active",
        )
    except ValueError:
        await store.update_experience(
            experience_id=experience_id,
            expected_status="active",
            status="invalidated",
        )
        raise
    if not chapters_replaced:
        raise ValueError("Draft experience changed during creation")
    await store.recompute_experience_counts(experience_id=experience_id)
    completed = await store.update_experience_draft(
        draft_id=draft_id,
        expected_status="editing",
        status="completed",
        created_experience_id=experience_id,
    )
    if not completed:
        await store.update_experience(
            experience_id=experience_id,
            expected_status="active",
            status="invalidated",
        )
        raise ValueError("Draft changed during creation")
    return experience_id


__all__ = ["create_experience_from_draft"]
