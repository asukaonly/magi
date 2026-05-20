"""GET /api/memory/stories — unified narrative feed."""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ....memory.l3.storage.review_operations import ALLOWED_REVIEW_STATES
from .dependencies import _resolve_unified_memory

logger = logging.getLogger(__name__)

INSIGHT_CATEGORIES = [
    "state_change",
    "trend_shift",
    "conflict_resolution",
    "task_reflection",
    "goal_refinement",
    "preference_emergence",
    "risk_escalation",
    "milestone_review",
]

TEMPORAL_CATEGORIES = ["day", "week", "month", "quarter", "year"]


_memory_override: Any = None


@contextmanager
def override_unified_memory_for_test(unified_memory: Any):
    global _memory_override
    _memory_override = unified_memory
    try:
        yield
    finally:
        _memory_override = None


def _get_memory() -> Any:
    if _memory_override is not None:
        return _memory_override
    return _resolve_unified_memory()


def _row_to_story_item(row: dict[str, Any]) -> dict[str, Any]:
    """Project a raw L3 summary row into a story-feed item."""
    return {
        "summary_id": row.get("summary_id") or row.get("id"),
        "summary_type": row.get("summary_type"),
        "summary_category": row.get("summary_category"),
        "title": row.get("title") or _derive_title(row),
        "content": row.get("content") or "",
        "period_start": row.get("period_start"),
        "period_end": row.get("period_end"),
        "updated_at": row.get("updated_at"),
        "review_state": row.get("review_state") or "neutral",
        "insight_key": row.get("insight_key"),
        "insight_metadata": row.get("insight_metadata") or {},
        "evidence_event_count": int(row.get("source_event_count") or 0),
    }


def _derive_title(row: dict[str, Any]) -> str:
    category = str(row.get("summary_category") or "")
    if category in TEMPORAL_CATEGORIES:
        return f"{category}_summary"
    return category or "story"


class ReviewPatch(BaseModel):
    review_state: str = Field(..., min_length=1)
    user_note: str | None = Field(
        default=None,
        description="When provided, sets or overwrites the stored user note inside insight_metadata. "
                    "When null or omitted, the existing note is left unchanged (this endpoint cannot clear notes).",
    )


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/stories")
    async def list_stories(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        unified = _get_memory()
        if unified is None or unified.l3 is None:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

        insights, temporal = await asyncio.gather(
            unified.l3.list_summaries_by_category(
                summary_categories=INSIGHT_CATEGORIES,
                limit=limit + offset + 50,
            ),
            unified.l3.list_summaries_by_category(
                summary_categories=TEMPORAL_CATEGORIES,
                limit=limit + offset + 50,
            ),
        )

        combined = [_row_to_story_item(r) for r in [*insights, *temporal]]
        combined.sort(
            key=lambda item: (
                0 if item["review_state"] == "pending_confirmation" else 1,
                -(item["period_end"] or item["updated_at"] or 0),
            )
        )
        sliced = combined[offset : offset + limit]
        return {
            "items": sliced,
            "total": len(combined),
            "limit": limit,
            "offset": offset,
        }

    @router.patch("/stories/{summary_id}/review")
    async def patch_review_state(summary_id: str, payload: ReviewPatch) -> dict[str, Any]:
        if payload.review_state not in ALLOWED_REVIEW_STATES:
            raise HTTPException(status_code=422, detail="invalid_review_state")
        unified = _get_memory()
        if unified is None or unified.l3 is None:
            raise HTTPException(status_code=503, detail="memory_unavailable")
        ok = await unified.l3.set_review_state(
            summary_id=summary_id,
            review_state=payload.review_state,
            user_note=payload.user_note,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="summary_not_found")
        return {"ok": True, "summary_id": summary_id, "review_state": payload.review_state}

    return router
