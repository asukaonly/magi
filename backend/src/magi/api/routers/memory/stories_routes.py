"""GET /api/memory/stories — unified narrative feed."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ....memory.l3.insight_utils import decode_value
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

# Extra rows fetched per category to allow cross-category interleaving:
# pending-first reordering can pull older insights ahead of newer temporal
# rows, so the visible window's top entries may live deeper in either feed.
_INTERLEAVE_HEADROOM = 50
_INTEREST_TREND_GROUP = "interest_profile"

# Detects schema identifiers that should never reach the user.
# Patterns like "state.sleep_quality", "engagement.gaming_focus" — lowercase
# letters separated by '.', optionally with underscores.
# Doesn't use \b because Chinese chars are word chars in Python 3 unicode regex,
# so a Chinese-letter / english-letter boundary doesn't trigger \b.
_TRAIT_LEAK_PATTERN = re.compile(r"(?<![a-zA-Z0-9])([a-z][a-z_]*\.[a-z][a-z_]+)(?![a-zA-Z0-9])")

# Safe-extension suffixes — file paths and URLs are not leak candidates.
_SAFE_EXTENSIONS = {
    "com", "org", "net", "io", "cn", "jp", "ai", "co", "dev", "app",
    "py", "ts", "tsx", "js", "jsx", "md", "html", "css", "json", "yaml", "yml",
    "sh", "txt", "log", "csv",
}


def _metadata_outcomes(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    outcomes = metadata.get("outcomes")
    if not isinstance(outcomes, list):
        return []
    return [outcome for outcome in outcomes if isinstance(outcome, dict)]


def _is_interest_trait_name(value: Any) -> bool:
    return str(value or "").strip().lower().startswith("interest.")


def _trend_groups_from_metadata(metadata: dict[str, Any]) -> list[str]:
    trend_groups = metadata.get("trend_groups")
    if isinstance(trend_groups, list):
        groups = [str(group).strip() for group in trend_groups if str(group).strip()]
        if groups:
            return groups

    outcomes = _metadata_outcomes(metadata)
    if outcomes and all(_is_interest_trait_name(outcome.get("trait_name")) for outcome in outcomes):
        return [_INTEREST_TREND_GROUP]
    return []


def _interest_values_from_metadata(metadata: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for outcome in _metadata_outcomes(metadata):
        raw_value = outcome.get("winning_value")
        if raw_value is None:
            raw_value = outcome.get("value")
        decoded_value = decode_value(raw_value) if isinstance(raw_value, str) else raw_value
        if isinstance(decoded_value, (dict, list)):
            value = json.dumps(decoded_value, ensure_ascii=False, sort_keys=True)
        else:
            value = str(decoded_value or "").strip()
        if not value:
            continue
        if value.casefold() in {item.casefold() for item in values}:
            continue
        values.append(value)
        if len(values) >= 6:
            break
    return values


def _is_interest_trend_item(item: dict[str, Any]) -> bool:
    if item.get("summary_category") != "trend_shift":
        return False
    metadata = item.get("insight_metadata")
    if not isinstance(metadata, dict):
        return False
    return _INTEREST_TREND_GROUP in _trend_groups_from_metadata(metadata)


def _render_interest_trend_content(metadata: dict[str, Any]) -> str | None:
    values = _interest_values_from_metadata(metadata)
    if not values:
        return None
    return f"最近持续关注：{'、'.join(values)}。"


def _trend_dedupe_key(item: dict[str, Any]) -> tuple[str, str] | None:
    if item.get("summary_category") != "trend_shift":
        return None
    metadata = item.get("insight_metadata")
    if not isinstance(metadata, dict):
        return None
    groups = _trend_groups_from_metadata(metadata)
    if not groups:
        return None
    entity_id = str(metadata.get("entity_id") or item.get("insight_key") or "").strip()
    if not entity_id:
        return None
    return (entity_id, "|".join(sorted(groups)))


def _latest_sort_key(item: dict[str, Any]) -> tuple[float, float]:
    period_end = item.get("period_end")
    updated_at = item.get("updated_at")
    return (
        float(period_end) if isinstance(period_end, (int, float)) else 0.0,
        float(updated_at) if isinstance(updated_at, (int, float)) else 0.0,
    )


def _dedupe_trend_shift_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed: dict[tuple[str, str], dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for item in items:
        key = _trend_dedupe_key(item)
        if key is None:
            unkeyed.append(item)
            continue
        existing = keyed.get(key)
        if existing is None or _latest_sort_key(item) > _latest_sort_key(existing):
            keyed[key] = item
    return [*unkeyed, *keyed.values()]


def _is_legible_insight_content(content: str) -> bool:
    """Return False when the content contains raw trait_name schema leakage.

    Used as a last-mile safety net against legacy L3 insight rows generated
    before the renderer chokepoint was in place.
    """
    matches = _TRAIT_LEAK_PATTERN.findall(content or "")
    if not matches:
        return True
    for match in matches:
        suffix = match.rsplit(".", 1)[-1]
        if suffix in _SAFE_EXTENSIONS:
            continue
        return False
    return True


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
    metadata = row.get("insight_metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError, ValueError):
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    salience_until_raw = metadata.get("salience_until")
    salience_until: float | None
    if isinstance(salience_until_raw, (int, float)):
        salience_until = float(salience_until_raw)
    else:
        salience_until = None
    content = row.get("content") or ""
    if str(row.get("summary_category") or "") == "trend_shift":
        trend_item = {"summary_category": "trend_shift", "insight_metadata": metadata}
        if _is_interest_trend_item(trend_item):
            rendered = _render_interest_trend_content(metadata)
            if rendered is not None:
                content = rendered
    return {
        "summary_id": row.get("summary_id") or row.get("id"),
        "summary_type": row.get("summary_type"),
        "summary_category": row.get("summary_category"),
        "title": row.get("title") or _derive_title(row),
        "content": content,
        "period_start": row.get("period_start"),
        "period_end": row.get("period_end"),
        "updated_at": row.get("updated_at"),
        "review_state": row.get("review_state") or "neutral",
        "insight_key": row.get("insight_key"),
        "insight_metadata": metadata,
        "evidence_event_count": int(row.get("source_event_count") or 0),
        "salience_until": salience_until,
    }


def _derive_title(row: dict[str, Any]) -> str:
    # When the L3 record has no human title we deliberately return "" so the
    # frontend can show the category chip + lede instead of a machine name.
    return ""


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


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/stories")
    async def list_stories(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        """Return a paginated unified narrative feed.

        ``total`` is the count of items the server merged for this request,
        bounded by the per-category fetch cap (``limit + offset + _INTERLEAVE_HEADROOM``).
        Treat it as a lower bound, not a true store-wide total. Clients
        that need to detect exhaustion should check ``len(items) < limit``.
        """
        unified = _get_memory()
        if unified is None or unified.l3 is None:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

        insights, temporal = await asyncio.gather(
            unified.l3.list_summaries_by_category(
                summary_categories=INSIGHT_CATEGORIES,
                limit=limit + offset + _INTERLEAVE_HEADROOM,
            ),
            unified.l3.list_summaries_by_category(
                summary_categories=TEMPORAL_CATEGORIES,
                limit=limit + offset + _INTERLEAVE_HEADROOM,
            ),
        )

        combined = [_row_to_story_item(r) for r in [*insights, *temporal]]

        # Hide insight cards whose content still contains raw trait_name
        # schema identifiers (legacy data predating the renderer chokepoint).
        combined = [
            item for item in combined
            if item["summary_type"] != "insight"
            or _is_legible_insight_content(item["content"])
        ]
        combined = _dedupe_trend_shift_items(combined)

        # Hide state_change insights whose salience window has passed.
        # Other insight categories (trend_shift, milestone_review, ...) and
        # temporal summaries are unaffected. salience_until=None means
        # "no expiry"; always keep those.
        _STATE_CLASS_CATEGORIES = {"state_change"}
        _now = time.time()
        combined = [
            item for item in combined
            if not (
                item["summary_category"] in _STATE_CLASS_CATEGORIES
                and item.get("salience_until") is not None
                and item["salience_until"] < _now
            )
        ]

        combined.sort(
            key=lambda item: (
                0 if item["review_state"] == "pending_confirmation" else 1,
                -(item["period_end"] or item["updated_at"] or 0),
            )
        )
        sliced = combined[offset : offset + limit]
        return {
            "items": sliced,
            # See docstring: bounded by fetch cap; treat as lower-bound, not store total.
            "total": len(combined),
            "limit": limit,
            "offset": offset,
        }

    @router.get("/stories/{summary_id}/evidence")
    async def get_story_evidence(
        summary_id: str,
        limit: int = Query(default=25, ge=1, le=100),
    ) -> dict[str, Any]:
        unified = _get_memory()
        if unified is None or unified.l3 is None:
            raise HTTPException(status_code=503, detail="memory_unavailable")

        # 1. Load the summary row.
        summary = await unified.l3.get_summary_by_id(summary_id)
        if summary is None:
            raise HTTPException(status_code=404, detail="summary_not_found")

        summary_type = str(summary.get("summary_type") or "")
        summary_category = str(summary.get("summary_category") or "")

        # 2. Resolve event IDs (or time window) to fetch.
        source_ids_raw = summary.get("source_event_ids") or []
        # source_event_ids is JSON-encoded TEXT in DB; the store layer may
        # decode it to list, or leave it as string. Handle both.
        if isinstance(source_ids_raw, str):
            try:
                source_ids = json.loads(source_ids_raw)
            except (json.JSONDecodeError, ValueError):
                source_ids = []
        elif isinstance(source_ids_raw, list):
            source_ids = source_ids_raw
        else:
            source_ids = []
        source_ids = [str(eid).strip() for eid in source_ids if str(eid).strip()]

        l1 = getattr(unified, "l1", None)
        if l1 is None:
            return {"summary_id": summary_id, "items": [], "mode": "no_l1"}

        events: list[dict[str, Any]] = []
        mode: str

        if summary_type == "temporal" or (summary_type != "insight" and not source_ids):
            # Time-window mode.
            period_start = summary.get("period_start")
            period_end = summary.get("period_end")
            if period_start is None or period_end is None:
                return {"summary_id": summary_id, "items": [], "mode": "no_window"}
            events = await l1.query_events(
                start_time=float(period_start),
                end_time=float(period_end),
                cognition_eligible=True,
                limit=limit,
                order_by="timestamp_desc",
                include_metadata_json=False,
                include_embedding_fields=False,
            )
            mode = "time_window"
        else:
            # ID-list mode (insight, or thematic with source IDs).
            for event_id in source_ids[:limit]:
                event = await l1.get_event(event_id)
                if event is not None:
                    events.append(event)
            mode = "source_ids"

        # 3. Project to a compact, frontend-friendly shape.
        items = [_project_evidence_event(event) for event in events]

        return {
            "summary_id": summary_id,
            "summary_type": summary_type,
            "summary_category": summary_category,
            "mode": mode,
            "items": items,
            "total": len(items),
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
