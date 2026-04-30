"""Shared utility functions for hybrid retrieval rerankers."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List


def _identifier_key_for_layer(layer: str) -> str:
    if layer == "L1":
        return "event_id"
    if layer == "L3":
        return "summary_id"
    if layer == "L4":
        return "skill_id"
    return "id"


def _secondary_timestamp(item: Dict[str, Any]) -> float:
    for key in ("timestamp", "updated_at", "created_at", "period_end"):
        value = item.get(key)
        if value is not None:
            return float(value)
    return 0.0


def _best_distance(item: Dict[str, Any], matched_chunks: List[Dict[str, Any]]) -> float | None:
    if item.get("distance") is not None:
        return float(item["distance"])
    if matched_chunks:
        distance = matched_chunks[0].get("distance")
        if distance is not None:
            return float(distance)
    return None


# Recency boost: alpha x exp(-lambda x days_ago)
# alpha = 0.15 (max bonus at t=0), lambda = 0.03 (half-life about 23 days)
_RECENCY_ALPHA = 0.15
_RECENCY_LAMBDA = 0.03


def _recency_bonus(timestamp: Any, *, now: float | None = None) -> float:
    """Return time-decay bonus for an item. Recent items score higher."""
    if timestamp is None:
        return 0.0
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return 0.0
    if ts <= 0:
        return 0.0
    if now is None:
        now = time.time()
    days_ago = max(0.0, (now - ts) / 86400.0)
    return _RECENCY_ALPHA * math.exp(-_RECENCY_LAMBDA * days_ago)


def _candidate_text_for_item(*, layer: str, item: Dict[str, Any], max_chars: int) -> str:
    matched_chunks = item.get("matched_chunks") if isinstance(item.get("matched_chunks"), list) else []
    best_chunk_text = ""
    if matched_chunks:
        best_chunk_text = str(
            matched_chunks[0].get("chunk_text") or matched_chunks[0].get("text") or ""
        ).strip()

    if layer == "L1":
        parts = [
            f"author_type: {item.get('author_type') or ''}",
            f"source: {item.get('source') or ''}",
            f"timestamp: {item.get('timestamp') or ''}",
            best_chunk_text or str(item.get("content") or ""),
        ]
    elif layer == "L3":
        parts = [
            f"summary_type: {item.get('summary_type') or ''}",
            f"summary_category: {item.get('summary_category') or ''}",
            best_chunk_text or str(item.get("content") or ""),
        ]
    elif layer == "L4":
        parts = [
            f"skill_name: {item.get('skill_name') or ''}",
            f"skill_category: {item.get('skill_category') or ''}",
            best_chunk_text or str(item.get("optimized_prompt") or item.get("content") or ""),
        ]
    else:
        parts = [best_chunk_text or str(item.get("content") or "")]

    text = "\n".join(part for part in parts if part and str(part).strip())
    return text[:max_chars]


__all__ = [
    "_best_distance",
    "_candidate_text_for_item",
    "_identifier_key_for_layer",
    "_recency_bonus",
    "_secondary_timestamp",
]
