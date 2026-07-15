"""Serialization helpers for L3 summary rows."""
from __future__ import annotations

import json
from typing import Any, Dict

import aiosqlite

from .schema import EMBEDDING_STATUS_DISABLED


def row_to_summary_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    return {
        "summary_id": str(row["summary_id"]),
        "summary_type": str(row["summary_type"]),
        "summary_category": str(row["summary_category"]),
        "period_start": float(row["period_start"]),
        "period_end": float(row["period_end"]),
        "content": str(row["content"]),
        "key_topics": json.loads(row["key_topics"] or "[]"),
        "key_entities": json.loads(row["key_entities"] or "[]"),
        "sentiment_summary": decode_optional_json(row["sentiment_summary"]),
        "change_and_pattern": decode_optional_json(row["change_and_pattern"]),
        "source_event_ids": json.loads(row["source_event_ids"] or "[]"),
        "source_event_count": int(row["source_event_count"]),
        "importance_aggregate": float(row["importance_aggregate"] or 0.0),
        "event_type_distribution": json.loads(row["event_type_distribution"] or "{}"),
        "generated_by_model": row["generated_by_model"],
        "generation_prompt": row["generation_prompt"],
        "generation_reason": row["generation_reason"],
        "insight_key": row["insight_key"],
        "review_state": row["review_state"],
        "insight_metadata": decode_optional_json(row["insight_metadata"]) or {},
        "narrative_style": str(row["narrative_style"]) if row["narrative_style"] else "default",
        "essence_prose": row["essence_prose"] if row["essence_prose"] else None,
        "embedding_status": str(row["embedding_status"] or EMBEDDING_STATUS_DISABLED),
        "embedding_profile_id": row["embedding_profile_id"],
        "embedding_chunk_count": int(row["embedding_chunk_count"] or 0),
        "last_embedded_at": float(row["last_embedded_at"]) if row["last_embedded_at"] is not None else None,
        "source_revision": int(row["source_revision"] or 0),
        "derivation_state": str(row["derivation_state"] or "current"),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def encode_optional_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def decode_optional_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value
