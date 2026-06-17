"""L2 episode API routes."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, Query, status

from magi.memory.l2.entities.maintenance import (
    SCHEDULE_ID_L2_MAINTENANCE,
    TARGET_KEY_L2_MAINTENANCE,
)
from magi.scheduler.contracts import ScheduledExecutionResult, ScheduledTargetType
from magi.scheduler.repository import ScheduleRepository
from magi.utils.runtime import get_runtime_paths

from ..dependencies import _resolve_unified_memory
from ..helpers import memory_t
from ..router import memory_router
from ..schemas import (
    EpisodeAnnotationRequest,
    EpisodeEventIdsRequest,
    EpisodeMergeRequest,
    EpisodeSplitRequest,
)
from .episode_review_helpers import (
    build_episode_display_fields,
    score_episode_candidate,
    score_event_candidate,
    serialize_episodic_summary,
    serialize_l1_event_preview,
)


def _l2_maintenance_lock_repository() -> ScheduleRepository:
    runtime_paths = get_runtime_paths()
    scheduler_db_path = getattr(
        runtime_paths,
        "scheduler_db_path",
        Path(runtime_paths.base_dir) / "runtime" / "scheduler.db",
    )
    return ScheduleRepository(scheduler_db_path)


async def _acquire_l2_maintenance_lock() -> ScheduleRepository:
    repository = _l2_maintenance_lock_repository()
    await repository.initialize()
    acquired = await repository.acquire_target_lock(
        ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        TARGET_KEY_L2_MAINTENANCE,
    )
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=memory_t(
                "memory.errors.l2_maintenance_busy",
                "L2 maintenance is already running",
            ),
        )
    return repository


async def _record_l2_maintenance_lock_success(
    repository: ScheduleRepository,
    *,
    stats: dict[str, Any],
) -> None:
    await repository.record_target_success(
        ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        TARGET_KEY_L2_MAINTENANCE,
        result=ScheduledExecutionResult(
            success=True,
            message="manual_reconsolidate_ok",
            stats=stats,
        ),
        scheduler_job_id=SCHEDULE_ID_L2_MAINTENANCE,
    )


async def _record_l2_maintenance_lock_failure(
    repository: ScheduleRepository,
    *,
    error: str,
) -> None:
    await repository.record_target_failure(
        ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        TARGET_KEY_L2_MAINTENANCE,
        error=error,
        scheduler_job_id=SCHEDULE_ID_L2_MAINTENANCE,
    )


def _serialize_episode_inference(assertion: Dict[str, Any]) -> Dict[str, Any]:
    """Return the episode-detail shape for an inferred assertion."""
    return {
        "assertion_id": assertion.get("assertion_id"),
        "entity_id": assertion.get("entity_id"),
        "entity_type": assertion.get("entity_type"),
        "trait_family": assertion.get("trait_family"),
        "trait_name": assertion.get("trait_name"),
        "trait_value": assertion.get("trait_value"),
        "confidence_score": assertion.get("confidence_score"),
        "natural_summary": assertion.get("natural_summary") or "",
        "validation_state": assertion.get("validation_state"),
        "user_feedback": assertion.get("user_feedback"),
        "evidence_events": list(assertion.get("evidence_events") or []),
    }


def _get_unified_layer(unified_memory: Any, name: str) -> Any:
    """Return an explicitly configured unified-memory layer, ignoring mock fallthrough."""
    attrs = getattr(unified_memory, "__dict__", {})
    if isinstance(attrs, dict) and name in attrs:
        return attrs[name]
    layer = getattr(unified_memory, name, None)
    if layer.__class__.__module__.startswith("unittest.mock"):
        return None
    return layer


async def _attach_episode_review_fields(
    unified_memory: Any,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach L3 summary and display fields to episode rows."""
    l3_store = _get_unified_layer(unified_memory, "l3")
    for item in items:
        episode_summary = None
        episode_id = str(item.get("episode_id") or "").strip()
        if l3_store is not None and episode_id:
            episode_summary = serialize_episodic_summary(
                await l3_store.get_episodic_summary_by_episode_id(episode_id)
            )
        item["episode_summary"] = episode_summary
        item.update(build_episode_display_fields(item, episode_summary))
    return items


async def _serialize_episode_event_previews(
    unified_memory: Any,
    event_memberships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    event_ids = [
        str(item.get("event_id") or "").strip()
        for item in event_memberships
        if item.get("event_id")
    ]
    l1_events_by_id: dict[str, dict[str, Any]] = {}
    l1_store = _get_unified_layer(unified_memory, "l1")
    if l1_store is not None and event_ids and hasattr(l1_store, "get_events_by_ids"):
        hydrated_events = await l1_store.get_events_by_ids(event_ids)
        l1_events_by_id = {
            str(item.get("event_id") or ""): item
            for item in hydrated_events
            if item.get("event_id")
        }

    events = [
        serialize_l1_event_preview(l1_events_by_id.get(str(item.get("event_id") or "")), membership=item)
        for item in event_memberships
    ]
    events.sort(key=lambda item: (
        item.get("timestamp") is None,
        float(item.get("timestamp") or item.get("added_at") or 0.0),
    ))
    return events


async def _regenerate_episode_summary(
    unified_memory: Any,
    *,
    episode: dict[str, Any],
    event_memberships: list[dict[str, Any]],
) -> dict[str, Any]:
    l1_store = _get_unified_layer(unified_memory, "l1")
    l3_store = _get_unified_layer(unified_memory, "l3")
    if l1_store is None or l3_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.summary_store_uninitialized", "Summary store not initialized"),
        )

    event_ids = [
        str(item.get("event_id") or "").strip()
        for item in event_memberships
        if item.get("event_id")
    ]
    if not event_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=memory_t("memory.errors.episode_has_no_events", "Episode has no events"),
        )

    summary = await l3_store.generate_episodic_summary(
        l1_store=l1_store,
        episode=episode,
        episode_event_ids=event_ids,
    )
    episode_summary = serialize_episodic_summary(summary)
    if episode_summary is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=memory_t("memory.errors.episode_summary_generation_failed", "Episode summary generation failed"),
        )
    await unified_memory.l2.index_episode_fts(
        episode_id=str(episode.get("episode_id") or ""),
        summary=episode_summary["content"],
        label=episode_summary["label"],
        user_label=str(episode.get("user_label") or ""),
    )
    return episode_summary


async def _build_episode_review_response(
    unified_memory: Any,
    *,
    episode: dict[str, Any],
    event_memberships: list[dict[str, Any]],
    episode_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if episode_summary is None:
        l3_store = _get_unified_layer(unified_memory, "l3")
        if l3_store is not None:
            episode_summary = serialize_episodic_summary(
                await l3_store.get_episodic_summary_by_episode_id(str(episode.get("episode_id") or ""))
            )
    display_fields = build_episode_display_fields(episode, episode_summary)
    events = await _serialize_episode_event_previews(unified_memory, event_memberships)
    inferred = await unified_memory.l2.list_assertions_for_episode(
        episode_id=str(episode.get("episode_id") or "")
    )
    return {
        **episode,
        **display_fields,
        "episode_summary": episode_summary,
        "events": events,
        "inferred": [_serialize_episode_inference(item) for item in inferred],
    }


async def _list_event_candidate_previews(
    unified_memory: Any,
    *,
    episode: dict[str, Any],
    current_memberships: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    l1_store = _get_unified_layer(unified_memory, "l1")
    if l1_store is None or not hasattr(l1_store, "query_events"):
        return []
    episode_id = str(episode.get("episode_id") or "")
    current_event_ids = {
        str(item.get("event_id") or "").strip()
        for item in current_memberships
        if item.get("event_id")
    }
    start = episode.get("time_start")
    end = episode.get("time_end")
    start_time = float(start) - 6 * 60 * 60 if isinstance(start, (int, float)) else None
    end_time = float(end) + 6 * 60 * 60 if isinstance(end, (int, float)) else None
    candidate_rows = await l1_store.query_events(
        start_time=start_time,
        end_time=end_time,
        limit=200,
        order_by="timestamp_asc",
    )
    previews: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in candidate_rows:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id or event_id in current_event_ids or event_id in seen:
            continue
        seen.add(event_id)
        score, reasons = score_event_candidate(episode, event)
        membership = {
            "episode_id": episode_id,
            "event_id": event_id,
            "membership_role": "candidate",
            "membership_confidence": min(1.0, max(0.0, score / 6.0)),
            "added_at": None,
        }
        preview = serialize_l1_event_preview(event, membership=membership)
        preview["candidate_score"] = score
        preview["candidate_reasons"] = reasons
        previews.append(preview)
    previews.sort(key=lambda item: (-float(item.get("candidate_score") or 0.0), float(item.get("timestamp") or 0.0)))
    return previews[:limit]


async def _refresh_episode_after_membership_change(
    unified_memory: Any,
    *,
    episode_id: str,
    event_memberships: list[dict[str, Any]],
) -> dict[str, Any]:
    event_ids = [
        str(item.get("event_id") or "").strip()
        for item in event_memberships
        if item.get("event_id")
    ]
    updates: dict[str, Any] = {"source_event_count": len(event_ids)}
    l1_store = _get_unified_layer(unified_memory, "l1")
    if l1_store is not None and event_ids and hasattr(l1_store, "get_events_by_ids"):
        events = await l1_store.get_events_by_ids(event_ids)
        timestamps = [
            float(event.get("timestamp"))
            for event in events
            if isinstance(event.get("timestamp"), (int, float))
        ]
        if timestamps:
            updates["time_start"] = min(timestamps)
            updates["time_end"] = max(timestamps)
    await unified_memory.l2.update_episode(episode_id=episode_id, **updates)
    episode = await unified_memory.l2.get_episode(episode_id=episode_id)
    return episode or {"episode_id": episode_id, **updates}


async def _try_regenerate_episode_summary(
    unified_memory: Any,
    *,
    episode: dict[str, Any],
    event_memberships: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if _get_unified_layer(unified_memory, "l1") is None or _get_unified_layer(unified_memory, "l3") is None:
        return None
    try:
        return await _regenerate_episode_summary(
            unified_memory,
            episode=episode,
            event_memberships=event_memberships,
        )
    except Exception:
        return None


def _event_time_bounds(
    events: list[dict[str, Any]],
    *,
    fallback_start: float,
    fallback_end: float,
) -> tuple[float, float]:
    values: list[float] = []
    for event in events:
        for key in ("timestamp", "added_at"):
            value = event.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
                break
    if not values:
        return fallback_start, fallback_end
    return min(values), max(values)


def _public_split_side(side: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_count": side["event_count"],
        "time_start": side["time_start"],
        "time_end": side["time_end"],
        "events": side["events"],
    }


async def _build_episode_split_preview(
    unified_memory: Any,
    *,
    episode_id: str,
    break_after_event_id: str,
) -> dict[str, Any]:
    episode = await unified_memory.l2.get_episode(episode_id=episode_id)
    if episode is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.episode_not_found", "Episode not found"),
        )

    memberships = await unified_memory.l2.list_episode_events(episode_id=episode_id)
    events = await _serialize_episode_event_previews(unified_memory, memberships)
    if len(events) < 2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=memory_t("memory.errors.episode_too_few_events", "Episode would have too few events"),
        )

    event_ids = [str(event.get("event_id") or "") for event in events]
    try:
        break_index = event_ids.index(break_after_event_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=memory_t("memory.errors.invalid_episode_split_breakpoint", "Invalid split breakpoint"),
        ) from exc
    if break_index >= len(events) - 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=memory_t("memory.errors.invalid_episode_split_breakpoint", "Invalid split breakpoint"),
        )

    left_events = events[: break_index + 1]
    right_events = events[break_index + 1 :]
    fallback_start = float(episode.get("time_start") or 0.0)
    fallback_end = float(episode.get("time_end") or fallback_start)
    left_time_start, left_time_end = _event_time_bounds(
        left_events,
        fallback_start=fallback_start,
        fallback_end=fallback_start,
    )
    right_time_start, right_time_end = _event_time_bounds(
        right_events,
        fallback_start=fallback_end,
        fallback_end=fallback_end,
    )
    return {
        "episode": episode,
        "left": {
            "event_count": len(left_events),
            "event_ids": [str(event.get("event_id") or "") for event in left_events],
            "time_start": left_time_start,
            "time_end": left_time_end,
            "events": left_events,
        },
        "right": {
            "event_count": len(right_events),
            "event_ids": [str(event.get("event_id") or "") for event in right_events],
            "time_start": right_time_start,
            "time_end": right_time_end,
            "events": right_events,
        },
    }


@memory_router.get("/l2/episodes")
async def list_l2_episodes(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    episode_type: Optional[str] = Query(default=None),
    time_start: Optional[float] = Query(default=None),
    time_end: Optional[float] = Query(default=None),
    parent_episode_id: Optional[str] = Query(default=None),
    surface: Optional[str] = Query(default=None, description="'standout' for canonical chapters"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List episodes with optional filters.

    When ``surface='standout'``, only ``magi_standout=1 OR user_pinned=1``
    episodes are returned, and each item carries a ``summary`` field with the
    linked L3 episodic summary (or null if not generated yet).
    """
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    if surface == "standout":
        items = await unified_memory.l2.list_standout_episodes(
            period_start=time_start,
            period_end=time_end,
            limit=limit,
        )
        await _attach_episode_review_fields(unified_memory, items)
        return {
            "items": items,
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "surface": "standout",
        }

    # Experience page default: show formed experiences, not only standouts.
    effective_status = status_filter if status_filter is not None else "active"
    items, total = await asyncio.gather(
        unified_memory.l2.list_episodes(
            status=effective_status,
            episode_type=episode_type,
            time_start=time_start,
            time_end=time_end,
            parent_episode_id=parent_episode_id,
            limit=limit,
            offset=offset,
        ),
        unified_memory.l2.count_episodes(status=effective_status),
    )
    await _attach_episode_review_fields(unified_memory, items)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@memory_router.get("/l2/episodes/search")
async def search_l2_episodes(
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Full-text search over episodes."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": []}
    items = await unified_memory.l2.search_episodes_fts(query=q, limit=limit)
    return {"items": items}


@memory_router.get("/l2/episodes/{episode_id}")
async def get_l2_episode(episode_id: str):
    """Get a single episode with its event memberships."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    episode = await unified_memory.l2.get_episode(episode_id=episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.episode_not_found", "Episode not found"))
    event_memberships, inferred = await asyncio.gather(
        unified_memory.l2.list_episode_events(episode_id=episode_id),
        unified_memory.l2.list_assertions_for_episode(episode_id=episode_id),
    )
    events = await _serialize_episode_event_previews(unified_memory, event_memberships)

    episode_summary = None
    l3_store = _get_unified_layer(unified_memory, "l3")
    if l3_store is not None:
        episode_summary = serialize_episodic_summary(
            await l3_store.get_episodic_summary_by_episode_id(episode_id)
        )
    display_fields = build_episode_display_fields(episode, episode_summary)

    return {
        **episode,
        **display_fields,
        "episode_summary": episode_summary,
        "events": events,
        "inferred": [_serialize_episode_inference(item) for item in inferred],
    }


@memory_router.post("/l2/episodes/{episode_id}/regenerate")
async def regenerate_l2_episode(episode_id: str):
    """Regenerate the L3 recap for an active episode and refresh review fields."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    episode = await unified_memory.l2.get_episode(episode_id=episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.episode_not_found", "Episode not found"))
    event_memberships = await unified_memory.l2.list_episode_events(episode_id=episode_id)
    episode_summary = await _regenerate_episode_summary(
        unified_memory,
        episode=episode,
        event_memberships=event_memberships,
    )
    display_fields = build_episode_display_fields(episode, episode_summary)
    events = await _serialize_episode_event_previews(unified_memory, event_memberships)
    inferred = await unified_memory.l2.list_assertions_for_episode(episode_id=episode_id)
    return {
        **episode,
        **display_fields,
        "episode_summary": episode_summary,
        "events": events,
        "inferred": [_serialize_episode_inference(item) for item in inferred],
    }


@memory_router.get("/l2/episodes/{episode_id}/event-candidates")
async def list_l2_episode_event_candidates(
    episode_id: str,
    limit: int = Query(default=20, ge=1, le=50),
):
    """List nearby or similar L1 events that can be added to an episode."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    episode = await unified_memory.l2.get_episode(episode_id=episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.episode_not_found", "Episode not found"))
    memberships = await unified_memory.l2.list_episode_events(episode_id=episode_id)
    items = await _list_event_candidate_previews(
        unified_memory,
        episode=episode,
        current_memberships=memberships,
        limit=limit,
    )
    return {"items": items}


@memory_router.post("/l2/episodes/{episode_id}/events")
async def add_l2_episode_events(episode_id: str, body: EpisodeEventIdsRequest):
    """Add candidate L1 events to an episode and refresh its recap."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    episode = await unified_memory.l2.get_episode(episode_id=episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.episode_not_found", "Episode not found"))

    current_memberships = await unified_memory.l2.list_episode_events(episode_id=episode_id)
    candidates = await _list_event_candidate_previews(
        unified_memory,
        episode=episode,
        current_memberships=current_memberships,
        limit=100,
    )
    candidate_ids = {str(item.get("event_id") or "") for item in candidates}
    requested_ids = [event_id for event_id in body.event_ids if event_id in candidate_ids]
    if len(requested_ids) != len(body.event_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=memory_t("memory.errors.invalid_episode_event_candidate", "Event is not an add candidate for this episode"),
        )

    await unified_memory.l2.add_episode_events(episode_id=episode_id, event_ids=requested_ids)
    updated_memberships = await unified_memory.l2.list_episode_events(episode_id=episode_id)
    updated_episode = await _refresh_episode_after_membership_change(
        unified_memory,
        episode_id=episode_id,
        event_memberships=updated_memberships,
    )
    episode_summary = await _try_regenerate_episode_summary(
        unified_memory,
        episode=updated_episode,
        event_memberships=updated_memberships,
    )
    return await _build_episode_review_response(
        unified_memory,
        episode=updated_episode,
        event_memberships=updated_memberships,
        episode_summary=episode_summary,
    )


@memory_router.delete("/l2/episodes/{episode_id}/events")
async def remove_l2_episode_events(episode_id: str, body: EpisodeEventIdsRequest):
    """Remove L1 events from an episode and refresh its recap."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    episode = await unified_memory.l2.get_episode(episode_id=episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.episode_not_found", "Episode not found"))
    current_memberships = await unified_memory.l2.list_episode_events(episode_id=episode_id)
    current_ids = [
        str(item.get("event_id") or "").strip()
        for item in current_memberships
        if item.get("event_id")
    ]
    remaining_ids = [event_id for event_id in current_ids if event_id not in set(body.event_ids)]
    if len(remaining_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=memory_t("memory.errors.episode_too_few_events", "Episode would have too few events"),
        )

    await unified_memory.l2.remove_episode_events(episode_id=episode_id, event_ids=body.event_ids)
    updated_memberships = await unified_memory.l2.list_episode_events(episode_id=episode_id)
    updated_episode = await _refresh_episode_after_membership_change(
        unified_memory,
        episode_id=episode_id,
        event_memberships=updated_memberships,
    )
    episode_summary = await _try_regenerate_episode_summary(
        unified_memory,
        episode=updated_episode,
        event_memberships=updated_memberships,
    )
    return await _build_episode_review_response(
        unified_memory,
        episode=updated_episode,
        event_memberships=updated_memberships,
        episode_summary=episode_summary,
    )


@memory_router.patch("/l2/episodes/{episode_id}")
async def annotate_l2_episode(episode_id: str, body: EpisodeAnnotationRequest):
    """User annotation on an episode (label, note, pin)."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    updates: Dict[str, Any] = {}
    if body.user_label is not None:
        updates["user_label"] = body.user_label
    if body.user_note is not None:
        updates["user_note"] = body.user_note
    if body.user_pinned is not None:
        updates["user_pinned"] = 1 if body.user_pinned else 0
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=memory_t("memory.errors.no_fields_to_update", "No fields to update"))
    ok = await unified_memory.l2.update_episode(episode_id=episode_id, **updates)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.episode_not_found", "Episode not found"))
    return await unified_memory.l2.get_episode(episode_id=episode_id)


@memory_router.get("/l2/episodes/{episode_id}/merge-candidates")
async def list_l2_episode_merge_candidates(
    episode_id: str,
    limit: int = Query(default=10, ge=1, le=50),
):
    """List nearby or similar active episodes that can be merged."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    episode = await unified_memory.l2.get_episode(episode_id=episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.episode_not_found", "Episode not found"))

    start = episode.get("time_start")
    end = episode.get("time_end")
    window_start = float(start) - 24 * 60 * 60 if isinstance(start, (int, float)) else None
    window_end = float(end) + 24 * 60 * 60 if isinstance(end, (int, float)) else None
    candidates = await unified_memory.l2.list_episodes(
        status="active",
        time_start=window_start,
        time_end=window_end,
        limit=max(50, limit * 5),
    )
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("episode_id") or "")
        if candidate_id == episode_id:
            continue
        score, reasons = score_episode_candidate(episode, candidate)
        if score <= 0:
            continue
        item = dict(candidate)
        item["candidate_score"] = score
        item["candidate_reasons"] = reasons
        items.append(item)
    items.sort(key=lambda item: (-float(item.get("candidate_score") or 0.0), float(item.get("time_start") or 0.0)))
    items = items[:limit]
    await _attach_episode_review_fields(unified_memory, items)
    return {"items": items}


@memory_router.post("/l2/episodes/{episode_id}/merge")
async def merge_l2_episode(episode_id: str, body: EpisodeMergeRequest):
    """Merge another episode into the target episode."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    if body.absorbed_id == episode_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=memory_t("memory.errors.same_episode_merge", "Cannot merge an episode into itself"),
        )

    merged = await unified_memory.l2.merge_episodes(
        survivor_id=episode_id,
        absorbed_id=body.absorbed_id,
    )
    if merged is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.episode_not_found", "Episode not found"),
        )
    event_memberships = await unified_memory.l2.list_episode_events(episode_id=episode_id)
    episode_summary = await _try_regenerate_episode_summary(
        unified_memory,
        episode=merged,
        event_memberships=event_memberships,
    )
    return await _build_episode_review_response(
        unified_memory,
        episode=merged,
        event_memberships=event_memberships,
        episode_summary=episode_summary,
    )


@memory_router.post("/l2/episodes/{episode_id}/split-preview")
async def preview_l2_episode_split(episode_id: str, body: EpisodeSplitRequest):
    """Preview a chronological split without mutating episode storage."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    preview = await _build_episode_split_preview(
        unified_memory,
        episode_id=episode_id,
        break_after_event_id=body.break_after_event_id,
    )
    return {
        "left": _public_split_side(preview["left"]),
        "right": _public_split_side(preview["right"]),
    }


@memory_router.post("/l2/episodes/{episode_id}/split")
async def split_l2_episode(episode_id: str, body: EpisodeSplitRequest):
    """Split an episode into two chronological child episodes."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    preview = await _build_episode_split_preview(
        unified_memory,
        episode_id=episode_id,
        break_after_event_id=body.break_after_event_id,
    )
    split_token = uuid.uuid4().hex[:8]
    left_id = f"{episode_id}_split_{split_token}_a"
    right_id = f"{episode_id}_split_{split_token}_b"
    result = await unified_memory.l2.split_episode(
        source_episode_id=episode_id,
        left_episode_id=left_id,
        right_episode_id=right_id,
        left_event_ids=preview["left"]["event_ids"],
        right_event_ids=preview["right"]["event_ids"],
        left_time_start=preview["left"]["time_start"],
        left_time_end=preview["left"]["time_end"],
        right_time_start=preview["right"]["time_start"],
        right_time_end=preview["right"]["time_end"],
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.episode_not_found", "Episode not found"),
        )

    left_episode = result["left"]
    right_episode = result["right"]
    left_memberships, right_memberships = await asyncio.gather(
        unified_memory.l2.list_episode_events(episode_id=str(left_episode["episode_id"])),
        unified_memory.l2.list_episode_events(episode_id=str(right_episode["episode_id"])),
    )
    left_summary, right_summary = await asyncio.gather(
        _try_regenerate_episode_summary(
            unified_memory,
            episode=left_episode,
            event_memberships=left_memberships,
        ),
        _try_regenerate_episode_summary(
            unified_memory,
            episode=right_episode,
            event_memberships=right_memberships,
        ),
    )
    left_response, right_response = await asyncio.gather(
        _build_episode_review_response(
            unified_memory,
            episode=left_episode,
            event_memberships=left_memberships,
            episode_summary=left_summary,
        ),
        _build_episode_review_response(
            unified_memory,
            episode=right_episode,
            event_memberships=right_memberships,
            episode_summary=right_summary,
        ),
    )
    return {
        "source_episode_id": episode_id,
        "items": [left_response, right_response],
    }


@memory_router.post("/l2/episodes/reconsolidate")
async def reconsolidate_episodes_endpoint():
    """One-shot: consolidate candidate→active + mark standouts + generate L3 summaries.

    For the governance "立即整理" button. Synchronous: returns when all summary
    generation has finished. Each LLM call has a 30s timeout; in the worst case
    this can take a while if many active episodes still lack a summary.

    Catch-up scope: every ``status='active'`` episode lacking an L3 episodic
    summary gets one generated (widened from the old standout-only filter), so
    pre-existing active episodes that never got a title are backfilled here.
    Eager generation on new promotes is handled by the maintenance scheduler.
    """
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )

    lock_repository = await _acquire_l2_maintenance_lock()
    try:
        from magi.memory.l2.episode_formation import consolidate_episodes
        stats = await consolidate_episodes(unified_memory.l2)

        summaries_generated = 0
        summary_errors: list[str] = []

        if unified_memory.l3 is not None and unified_memory.l1 is not None:
            # Catch-up: every active episode lacking an L3 episodic summary (newly
            # promoted ones are already 'active', so they are included here).
            active_episodes = await unified_memory.l2.list_episodes(status="active", limit=500)
            episode_ids = [
                str(ep.get("episode_id") or "").strip()
                for ep in active_episodes
                if ep.get("episode_id")
            ]
            result = await unified_memory.l3.generate_missing_episodic_summaries(
                l1_store=unified_memory.l1,
                l2_store=unified_memory.l2,
                episode_ids=episode_ids,
            )
            summaries_generated = int(result.get("generated") or 0)
            summary_errors = list(result.get("errors") or [])

        response = {
            "promoted": stats.promoted,
            "standouts": stats.standouts,
            "merged": stats.merged,
            "invalidated": stats.invalidated,
            "summaries_generated": summaries_generated,
            "summary_errors": summary_errors,
        }
    except asyncio.CancelledError:
        await _record_l2_maintenance_lock_failure(
            lock_repository,
            error="manual_reconsolidate_cancelled",
        )
        raise
    except Exception as exc:
        await _record_l2_maintenance_lock_failure(lock_repository, error=str(exc))
        raise

    await _record_l2_maintenance_lock_success(lock_repository, stats=response)
    return response
