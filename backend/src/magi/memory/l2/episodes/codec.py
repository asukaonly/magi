"""Row decoding helpers for L2 episode persistence."""

from __future__ import annotations

import json
from typing import Any, Dict

import aiosqlite


class L2EpisodeStoreBaseMixin:
    """Shared base for L2 episode persistence mixins."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    def _episode_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "episode_id": str(row["episode_id"]),
            "episode_type": str(row["episode_type"]),
            "status": str(row["status"]),
            "time_start": float(row["time_start"]),
            "time_end": float(row["time_end"]),
            "parent_episode_id": str(row["parent_episode_id"]) if row["parent_episode_id"] else None,
            "label": str(row["label"]) if row["label"] else None,
            "summary": str(row["summary"]) if row["summary"] else None,
            "dominant_mode": str(row["dominant_mode"]) if row["dominant_mode"] else None,
            "primary_entity_ids": json.loads(row["primary_entity_ids"] or "[]"),
            "primary_place_ids": json.loads(row["primary_place_ids"] or "[]"),
            "primary_topic_keys": json.loads(row["primary_topic_keys"] or "[]"),
            "continuity_signals": json.loads(row["continuity_signals"] or "[]"),
            "formation_method": str(row["formation_method"]),
            "confidence": float(row["confidence"]),
            "source_event_count": int(row["source_event_count"]),
            "user_label": str(row["user_label"]) if row["user_label"] else None,
            "user_note": str(row["user_note"]) if row["user_note"] else None,
            "user_pinned": bool(row["user_pinned"]),
            "embedding_status": str(row["embedding_status"]),
            "embedding_profile_id": str(row["embedding_profile_id"]) if row["embedding_profile_id"] else None,
            "last_embedded_at": float(row["last_embedded_at"]) if row["last_embedded_at"] else None,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "last_recomputed_at": float(row["last_recomputed_at"]) if row["last_recomputed_at"] else None,
            # Immersive text fields: empty string (not None) to match EpisodeWrite.__post_init__ contract.
            "slice_narrative": str(row["slice_narrative"]) if row["slice_narrative"] else "",
            "slice_sensory_detail": str(row["slice_sensory_detail"]) if row["slice_sensory_detail"] else "",
            "magi_standout": bool(row["magi_standout"]),
            "standout_score": float(row["standout_score"]),
            "standout_reason": str(row["standout_reason"]) if row["standout_reason"] else "",
            "representative_asset_ref": str(row["representative_asset_ref"]) if row["representative_asset_ref"] else "",
        }


__all__ = ["L2EpisodeStoreBaseMixin"]
