"""Row decoding helpers for L2 experience persistence."""

from __future__ import annotations

import json
from typing import Any

import aiosqlite


def _row_has(row: aiosqlite.Row, key: str) -> bool:
    return key in row.keys()


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
            "source_seed_id": (
                str(row["source_seed_id"])
                if _row_has(row, "source_seed_id") and row["source_seed_id"]
                else None
            ),
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
            "user_cover_asset_ref": (
                str(row["user_cover_asset_ref"])
                if _row_has(row, "user_cover_asset_ref") and row["user_cover_asset_ref"]
                else None
            ),
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

    def _experience_seed_row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "seed_id": str(row["seed_id"]),
            "seed_type": str(row["seed_type"]),
            "status": str(row["status"]),
            "title": str(row["title"]) if row["title"] else None,
            "description": str(row["description"]) if row["description"] else None,
            "anchor_entity_ids": json.loads(row["anchor_entity_ids"] or "[]"),
            "anchor_place_ids": json.loads(row["anchor_place_ids"] or "[]"),
            "anchor_topic_keys": json.loads(row["anchor_topic_keys"] or "[]"),
            "time_start": float(row["time_start"]) if row["time_start"] is not None else None,
            "time_end": float(row["time_end"]) if row["time_end"] is not None else None,
            "confidence": float(row["confidence"] or 0.0),
            "created_by": str(row["created_by"]),
            "source_ref_type": str(row["source_ref_type"]) if row["source_ref_type"] else None,
            "source_ref_id": str(row["source_ref_id"]) if row["source_ref_id"] else None,
            "promoted_experience_id": (
                str(row["promoted_experience_id"]) if row["promoted_experience_id"] else None
            ),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "last_evaluated_at": (
                float(row["last_evaluated_at"]) if row["last_evaluated_at"] else None
            ),
        }

    def _experience_seed_evidence_row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "seed_id": str(row["seed_id"]),
            "ref_type": str(row["ref_type"]),
            "ref_id": str(row["ref_id"]),
            "role": str(row["role"]),
            "confidence": float(row["confidence"] or 0.0),
            "reason": str(row["reason"]) if row["reason"] else None,
            "created_at": float(row["created_at"]),
        }

    def _experience_draft_row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "draft_id": str(row["draft_id"]),
            "status": str(row["status"]),
            "query_text": str(row["query_text"]),
            "title": str(row["title"]),
            "one_sentence_review": str(row["one_sentence_review"]),
            "time_start": float(row["time_start"]),
            "time_end": float(row["time_end"]),
            "chapters": json.loads(row["chapters_json"] or "[]"),
            "possible_evidence": json.loads(row["possible_evidence_json"] or "[]"),
            "excluded_evidence": json.loads(row["excluded_evidence_json"] or "[]"),
            "user_cover_asset_ref": (
                str(row["user_cover_asset_ref"])
                if _row_has(row, "user_cover_asset_ref") and row["user_cover_asset_ref"]
                else None
            ),
            "created_experience_id": (
                str(row["created_experience_id"])
                if row["created_experience_id"]
                else None
            ),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _experience_chapter_row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "chapter_id": str(row["chapter_id"]),
            "title": str(row["title"]),
            "summary": str(row["summary"]),
            "time_start": float(row["time_start"]) if row["time_start"] is not None else None,
            "time_end": float(row["time_end"]) if row["time_end"] is not None else None,
            "episode_ids": json.loads(row["episode_ids_json"] or "[]"),
            "event_ids": json.loads(row["event_ids_json"] or "[]"),
        }


__all__ = ["L2ExperienceStoreBaseMixin"]
