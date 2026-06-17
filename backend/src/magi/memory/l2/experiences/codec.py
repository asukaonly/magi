"""Row decoding helpers for L2 experience persistence."""

from __future__ import annotations

import json
from typing import Any

import aiosqlite


class L2ExperienceStoreBaseMixin:
    """Shared base for L2 experience persistence mixins."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    def _experience_row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "experience_id": str(row["experience_id"]),
            "status": str(row["status"]),
            "title": str(row["title"]) if row["title"] else None,
            "time_start": float(row["time_start"]),
            "time_end": float(row["time_end"]),
            "experience_type": str(row["experience_type"]) if row["experience_type"] else None,
            "intent": str(row["intent"]) if row["intent"] else None,
            "outcome": str(row["outcome"]) if row["outcome"] else None,
            "magi_interpretation": (
                str(row["magi_interpretation"]) if row["magi_interpretation"] else None
            ),
            "narrative_score": float(row["narrative_score"] or 0.0),
            "primary_entity_ids": json.loads(row["primary_entity_ids"] or "[]"),
            "primary_place_ids": json.loads(row["primary_place_ids"] or "[]"),
            "primary_topic_keys": json.loads(row["primary_topic_keys"] or "[]"),
            "source_episode_count": int(row["source_episode_count"] or 0),
            "source_event_count": int(row["source_event_count"] or 0),
            "parent_experience_id": (
                str(row["parent_experience_id"]) if row["parent_experience_id"] else None
            ),
            "merged_into_experience_id": (
                str(row["merged_into_experience_id"])
                if row["merged_into_experience_id"]
                else None
            ),
            "user_label": str(row["user_label"]) if row["user_label"] else None,
            "user_note": str(row["user_note"]) if row["user_note"] else None,
            "user_pinned": bool(row["user_pinned"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "last_recomputed_at": (
                float(row["last_recomputed_at"]) if row["last_recomputed_at"] else None
            ),
        }

    def _experience_member_row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "experience_id": str(row["experience_id"]),
            "member_type": str(row["member_type"]),
            "member_id": str(row["member_id"]),
            "role": str(row["role"]),
            "confidence": float(row["confidence"]),
            "added_at": float(row["added_at"]),
        }


__all__ = ["L2ExperienceStoreBaseMixin"]
