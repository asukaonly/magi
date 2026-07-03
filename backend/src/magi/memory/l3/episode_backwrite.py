"""Back-write L3 episodic summaries onto L2 episode rows.

The scheduled consolidation path stores episodic summaries in the L3
``summaries`` table only; without back-writing, episode ``label`` /
``summary`` columns stay empty and the episode FTS index never gets
content for machine-formed episodes. These helpers copy the generated
label/content onto the episode row and refresh its FTS entry.
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


def episode_needs_summary_backfill(episode: dict[str, Any]) -> bool:
    """True when the episode row has no generated label/summary yet."""
    return not str(episode.get("label") or "").strip() and not str(
        episode.get("summary") or ""
    ).strip()


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
                label=label,
                summary=content,
            )
        )
    index_fts = getattr(l2_store, "index_episode_fts", None)
    if callable(index_fts):
        await index_fts(
            episode_id=episode_id,
            summary=content,
            label=label,
            user_label=str(episode.get("user_label") or ""),
        )
    return bool(updated)


__all__ = [
    "backwrite_episode_summary",
    "episode_needs_summary_backfill",
    "summary_display_fields",
]
