"""GET /api/memory/stories — unified narrative feed."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ....memory.l3.storage.review_operations import ALLOWED_REVIEW_STATES
from .dependencies import _resolve_unified_memory
from .story_feed_projection import (
    INSIGHT_CATEGORIES,
    TEMPORAL_CATEGORIES,
    build_story_feed_stats,
    empty_story_feed_stats,
    filter_story_feed_items,
    prepare_story_feed_items,
)

# Extra rows fetched per category to allow cross-category interleaving:
# pending-first reordering can pull older insights ahead of newer temporal
# rows, so the visible window's top entries may live deeper in either feed.
_INTERLEAVE_HEADROOM = 50


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


def _project_evidence_event(event: dict[str, Any]) -> dict[str, Any]:
    """Compact L1 event projection for the evidence rail.

    Keeps timestamp, source, type, and a content preview — drops embeddings,
    raw metadata blobs, and identity fields the UI doesn't surface.
    """
    content = str(event.get("content") or "")
    if len(content) > 240:
        content = content[:240].rstrip() + "..."
    return {
        "event_id": event.get("event_id"),
        "timestamp": event.get("timestamp"),
        "source": event.get("source"),
        "event_type": event.get("event_type"),
        "memory_domain": event.get("memory_domain"),
        "content": content,
    }


class ReviewPatch(BaseModel):
    review_state: str = Field(..., min_length=1)
    user_note: str | None = Field(
        default=None,
        description="When provided, sets or overwrites the stored user note inside insight_metadata. "
        "When null or omitted, the existing note is left unchanged (this endpoint cannot clear notes).",
    )


def _empty_story_response(limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
        "stats": empty_story_feed_stats(),
    }


async def _list_story_feed(
    *,
    limit: int,
    offset: int,
    surface: Literal["all", "summary"],
    group: Literal["periodic", "observations", "tasks", "other"] | None,
) -> dict[str, Any]:
    unified = _get_memory()
    if unified is None or unified.l3 is None:
        return _empty_story_response(limit, offset)

    fetch_limit = limit + offset + _INTERLEAVE_HEADROOM
    insights, temporal = await asyncio.gather(
        unified.l3.list_summaries_by_category(
            summary_categories=INSIGHT_CATEGORIES,
            limit=fetch_limit,
        ),
        unified.l3.list_summaries_by_category(
            summary_categories=TEMPORAL_CATEGORIES,
            limit=fetch_limit,
        ),
    )

    combined = prepare_story_feed_items([*insights, *temporal])
    stats = build_story_feed_stats(combined)
    visible = filter_story_feed_items(combined, surface=surface, group=group)
    sliced = visible[offset : offset + limit]
    return {
        "items": sliced,
        # Bounded by fetch cap; treat as lower-bound, not store total.
        "total": len(visible),
        "limit": limit,
        "offset": offset,
        "stats": stats,
    }


def _source_event_ids(summary: dict[str, Any]) -> list[str]:
    source_ids_raw = summary.get("source_event_ids") or []
    if isinstance(source_ids_raw, str):
        try:
            source_ids = json.loads(source_ids_raw)
        except (json.JSONDecodeError, ValueError):
            source_ids = []
    elif isinstance(source_ids_raw, list):
        source_ids = source_ids_raw
    else:
        source_ids = []
    return [str(event_id).strip() for event_id in source_ids if str(event_id).strip()]


def _uses_time_window(summary_type: str, source_ids: list[str]) -> bool:
    return summary_type != "insight" and not source_ids


async def _time_window_evidence(
    *,
    l1: Any,
    summary: dict[str, Any],
    limit: int,
) -> tuple[list[dict[str, Any]], str]:
    period_start = summary.get("period_start")
    period_end = summary.get("period_end")
    if period_start is None or period_end is None:
        return [], "no_window"
    events = await l1.query_events(
        start_time=float(period_start),
        end_time=float(period_end),
        cognition_eligible=True,
        limit=limit,
        order_by="timestamp_desc",
        include_metadata_json=False,
        include_embedding_fields=False,
    )
    return events, "time_window"


async def _source_id_evidence(
    *,
    l1: Any,
    source_ids: list[str],
    limit: int,
) -> tuple[list[dict[str, Any]], str]:
    events: list[dict[str, Any]] = []
    for event_id in source_ids[:limit]:
        event = await l1.get_event(event_id)
        if event is not None:
            events.append(event)
    return events, "source_ids"


async def _resolve_evidence_events(
    *,
    unified: Any,
    summary: dict[str, Any],
    summary_type: str,
    source_ids: list[str],
    limit: int,
) -> tuple[list[dict[str, Any]], str]:
    l1 = getattr(unified, "l1", None)
    if l1 is None:
        return [], "no_l1"
    if _uses_time_window(summary_type, source_ids):
        return await _time_window_evidence(l1=l1, summary=summary, limit=limit)
    return await _source_id_evidence(l1=l1, source_ids=source_ids, limit=limit)


async def _get_story_evidence(summary_id: str, limit: int) -> dict[str, Any]:
    unified = _get_memory()
    if unified is None or unified.l3 is None:
        raise HTTPException(status_code=503, detail="memory_unavailable")

    summary = await unified.l3.get_summary_by_id(summary_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="summary_not_found")

    summary_type = str(summary.get("summary_type") or "")
    summary_category = str(summary.get("summary_category") or "")
    source_ids = _source_event_ids(summary)
    events, mode = await _resolve_evidence_events(
        unified=unified,
        summary=summary,
        summary_type=summary_type,
        source_ids=source_ids,
        limit=limit,
    )
    if mode in {"no_l1", "no_window"}:
        return {"summary_id": summary_id, "items": [], "mode": mode}

    items = [_project_evidence_event(event) for event in events]
    return {
        "summary_id": summary_id,
        "summary_type": summary_type,
        "summary_category": summary_category,
        "mode": mode,
        "items": items,
        "total": len(items),
    }


async def _patch_story_review(summary_id: str, payload: ReviewPatch) -> dict[str, Any]:
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


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/stories")
    async def list_stories(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        surface: Literal["all", "summary"] = Query(default="all"),
        group: Literal["periodic", "observations", "tasks", "other"] | None = Query(default=None),
    ) -> dict[str, Any]:
        """Return a paginated unified narrative feed.

        ``total`` is the count of items the server merged for this request,
        bounded by the per-category fetch cap (``limit + offset + _INTERLEAVE_HEADROOM``).
        Treat it as a lower bound, not a true store-wide total. Clients
        that need to detect exhaustion should check ``len(items) < limit``.
        """
        return await _list_story_feed(
            limit=limit,
            offset=offset,
            surface=surface,
            group=group,
        )

    @router.get("/stories/{summary_id}/evidence")
    async def get_story_evidence(
        summary_id: str,
        limit: int = Query(default=25, ge=1, le=100),
    ) -> dict[str, Any]:
        return await _get_story_evidence(summary_id=summary_id, limit=limit)

    @router.patch("/stories/{summary_id}/review")
    async def patch_review_state(summary_id: str, payload: ReviewPatch) -> dict[str, Any]:
        return await _patch_story_review(summary_id=summary_id, payload=payload)

    return router
