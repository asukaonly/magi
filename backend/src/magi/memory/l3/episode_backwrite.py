"""Back-write L3 episodic summaries onto L2 episode/experience rows.

The scheduled consolidation path stores episodic summaries in the L3
``summaries`` table only; without back-writing, episode ``label`` /
``summary`` columns stay empty and the episode FTS index never gets
content for machine-formed episodes. These helpers copy the generated
label/content onto the L2 row and refresh its search-facing text where
needed.
"""

from __future__ import annotations

import json
from typing import Any


def _metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _summary_content_text(value: Any) -> str:
    """Return prose content, tolerating legacy JSON-payload content blobs."""
    if isinstance(value, str):
        text = value.strip()
        if not text.startswith("{"):
            return text
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return text
        if isinstance(decoded, dict):
            for key in ("content", "summary", "description", "recap", "text"):
                nested = str(decoded.get(key) or "").strip()
                if nested:
                    return nested
            return ""
        return text
    if isinstance(value, dict):
        for key in ("content", "summary", "description", "recap", "text"):
            nested = str(value.get(key) or "").strip()
            if nested:
                return nested
        return ""
    return str(value or "").strip()


def summary_display_fields(summary: dict[str, Any]) -> tuple[str, str]:
    """Extract (label, content) display fields from an L3 summary row."""
    metadata = _metadata_dict(summary.get("insight_metadata"))
    label = str(metadata.get("label") or "").strip()
    content = _summary_content_text(summary.get("content"))
    return label, content


def _experience_generated_field_needs_backwrite(
    experience: dict[str, Any],
    field_name: str,
) -> bool:
    text = str(experience.get(field_name) or "").strip()
    if not text:
        return True
    title = str(experience.get("title") or "").strip()
    return bool(title) and text.casefold() == title.casefold()


def episode_needs_summary_backfill(episode: dict[str, Any]) -> bool:
    """True when the episode row has no generated label/summary yet."""
    return (
        not str(episode.get("label") or "").strip()
        and not str(episode.get("summary") or "").strip()
    )


async def backwrite_episode_summary(
    l2_store: Any,
    *,
    episode: dict[str, Any],
    summary: dict[str, Any],
) -> bool:
    """Copy summary label/content onto the episode row and refresh FTS.

    Returns True when the episode row was updated.
    """
    episode_id = str(episode.get("episode_id") or "").strip()
    if not episode_id:
        return False
    label, content = summary_display_fields(summary)
    if not label and not content:
        return False

    updated = False
    update_episode = getattr(l2_store, "update_episode", None)
    if callable(update_episode):
        updated = bool(
            await update_episode(
                episode_id=episode_id,
                expected_status="active",
                label=label,
                summary=content,
            )
        )
    index_fts = getattr(l2_store, "index_episode_fts", None)
    if updated and callable(index_fts):
        await index_fts(
            episode_id=episode_id,
            summary=content,
            label=label,
            user_label=str(episode.get("user_label") or ""),
        )
    return bool(updated)


async def backwrite_experience_review(
    l2_store: Any,
    *,
    experience: dict[str, Any],
    summary: dict[str, Any],
) -> bool:
    """Copy a non-fallback L3 review onto generated L2 experience fields.

    User-owned fields stay independent: callers render ``user_label`` and
    ``user_note`` ahead of generated fields. The generated fields are refreshed
    so retrieval sees the same latest review text as the product surface.
    """
    experience_id = str(experience.get("experience_id") or "").strip()
    if not experience_id:
        return False
    metadata = _metadata_dict(summary.get("insight_metadata"))
    if metadata.get("fallback"):
        return False

    label, content = summary_display_fields(summary)
    updates: dict[str, Any] = {}
    if label:
        updates["title"] = label
    if content:
        updates["magi_interpretation"] = content
    intent = str(metadata.get("intent") or "").strip()
    if intent and _experience_generated_field_needs_backwrite(experience, "intent"):
        updates["intent"] = intent
    outcome = str(metadata.get("outcome") or "").strip()
    if outcome and _experience_generated_field_needs_backwrite(experience, "outcome"):
        updates["outcome"] = outcome
    if not updates:
        return False

    update_experience = getattr(l2_store, "update_experience", None)
    if not callable(update_experience):
        return False
    return bool(
        await update_experience(
            experience_id=experience_id,
            expected_status="active",
            **updates,
        )
    )


__all__ = [
    "backwrite_experience_review",
    "backwrite_episode_summary",
    "episode_needs_summary_backfill",
    "summary_display_fields",
]
