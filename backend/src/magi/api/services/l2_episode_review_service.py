"""API-facing L2 episode review workflow service."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from magi.config import get_config
from magi.api.routers.memory.helpers import memory_t
from magi.api.services.l2_episode_review_helpers import (
    build_episode_display_fields,
    score_episode_candidate,
    score_event_candidate,
    serialize_episodic_summary,
    serialize_l1_event_preview,
)
from magi.api.services.l2_episode_review_read_model import (
    attach_episode_entity_previews,
    fetch_l1_events_by_ids,
    get_unified_layer,
    serialize_episode_event_previews as build_episode_event_previews,
)
from magi.memory.l2.consolidation_schedule import (
    SCHEDULE_ID_L2_CONSOLIDATE,
    TARGET_KEY_L2_CONSOLIDATE,
)
from magi.memory.l2.experiences.seed_selection_llm import (
    build_experience_seed_selector,
    scenario_llm_pool_from_unified_memory,
)
from magi.scheduler.contracts import ScheduledExecutionResult, ScheduledTargetType
from magi.scheduler.repository import ScheduleRepository
from magi.utils.runtime import get_runtime_paths


class L2EpisodeReviewService:
    """Coordinate API-level episode review workflows across L1, L2, and L3."""

    def __init__(self, unified_memory: Any) -> None:
        self._memory = unified_memory

    async def list_episodes(
        self,
        *,
        status_filter: str | None,
        episode_type: str | None,
        time_start: float | None,
        time_end: float | None,
        parent_episode_id: str | None,
        surface: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        if (status_filter or "").strip().lower() == "invalidated":
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

        if surface == "standout":
            items = await self._memory.l2.list_standout_episodes(
                period_start=time_start,
                period_end=time_end,
                limit=limit,
            )
            await self.attach_episode_review_fields(items)
            return {
                "items": items,
                "total": len(items),
                "limit": limit,
                "offset": offset,
                "surface": "standout",
            }

        effective_status = status_filter if status_filter is not None else "active"
        items, total = await asyncio.gather(
            self._memory.l2.list_episodes(
                status=effective_status,
                episode_type=episode_type,
                time_start=time_start,
                time_end=time_end,
                parent_episode_id=parent_episode_id,
                limit=limit,
                offset=offset,
            ),
            self._memory.l2.count_episodes(status=effective_status),
        )
        await self.attach_episode_review_fields(items)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    async def get_episode_review(self, episode_id: str) -> dict[str, Any]:
        episode = await self._get_episode_or_404(episode_id)
        event_memberships = await self._memory.l2.list_episode_events(episode_id=episode_id)
        return await self.build_episode_review_response(
            episode=episode,
            event_memberships=event_memberships,
        )

    async def regenerate_episode_review(self, episode_id: str) -> dict[str, Any]:
        episode = await self._get_episode_or_404(episode_id)
        event_memberships = await self._memory.l2.list_episode_events(episode_id=episode_id)
        episode_summary = await self.regenerate_episode_summary(
            episode=episode,
            event_memberships=event_memberships,
        )
        return await self.build_episode_review_response(
            episode=episode,
            event_memberships=event_memberships,
            episode_summary=episode_summary,
        )

    async def list_event_candidates(self, *, episode_id: str, limit: int) -> dict[str, Any]:
        episode = await self._get_episode_or_404(episode_id)
        memberships = await self._memory.l2.list_episode_events(episode_id=episode_id)
        items = await self.list_event_candidate_previews(
            episode=episode,
            current_memberships=memberships,
            limit=limit,
        )
        return {"items": items}

    async def add_episode_events(self, *, episode_id: str, event_ids: list[str]) -> dict[str, Any]:
        episode = await self._get_episode_or_404(episode_id)
        current_memberships = await self._memory.l2.list_episode_events(episode_id=episode_id)
        candidates = await self.list_event_candidate_previews(
            episode=episode,
            current_memberships=current_memberships,
            limit=100,
        )
        candidate_ids = {str(item.get("event_id") or "") for item in candidates}
        requested_ids = [event_id for event_id in event_ids if event_id in candidate_ids]
        if len(requested_ids) != len(event_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=memory_t(
                    "memory.errors.invalid_episode_event_candidate",
                    "Event is not an add candidate for this episode",
                ),
            )

        await self._memory.l2.add_episode_events(
            episode_id=episode_id,
            event_ids=requested_ids,
            expected_status="active",
        )
        return await self._refresh_after_episode_event_change(episode_id)

    async def remove_episode_events(
        self, *, episode_id: str, event_ids: list[str]
    ) -> dict[str, Any]:
        await self._get_episode_or_404(episode_id)
        current_memberships = await self._memory.l2.list_episode_events(episode_id=episode_id)
        current_ids = [
            str(item.get("event_id") or "").strip()
            for item in current_memberships
            if item.get("event_id")
        ]
        remaining_ids = [event_id for event_id in current_ids if event_id not in set(event_ids)]
        if len(remaining_ids) < 2:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=memory_t(
                    "memory.errors.episode_too_few_events", "Episode would have too few events"
                ),
            )

        await self._memory.l2.remove_episode_events(
            episode_id=episode_id,
            event_ids=event_ids,
            expected_status="active",
        )
        return await self._refresh_after_episode_event_change(episode_id)

    async def annotate_episode(
        self,
        *,
        episode_id: str,
        user_label: str | None,
        user_note: str | None,
        user_pinned: bool | None,
    ) -> dict[str, Any] | None:
        updates: dict[str, Any] = {}
        if user_label is not None:
            updates["user_label"] = user_label
        if user_note is not None:
            updates["user_note"] = user_note
        if user_pinned is not None:
            updates["user_pinned"] = 1 if user_pinned else 0
        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=memory_t("memory.errors.no_fields_to_update", "No fields to update"),
            )
        await self._get_episode_or_404(episode_id)
        ok = await self._memory.l2.update_episode(
            episode_id=episode_id,
            expected_status="active",
            **updates,
        )
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=memory_t("memory.errors.episode_not_found", "Episode not found"),
            )
        return await self._get_episode_or_404(episode_id)

    async def list_merge_candidates(self, *, episode_id: str, limit: int) -> dict[str, Any]:
        episode = await self._get_episode_or_404(episode_id)
        start = episode.get("time_start")
        end = episode.get("time_end")
        window_start = float(start) - 24 * 60 * 60 if isinstance(start, (int, float)) else None
        window_end = float(end) + 24 * 60 * 60 if isinstance(end, (int, float)) else None
        candidates = await self._memory.l2.list_episodes(
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
        items.sort(
            key=lambda item: (
                -float(item.get("candidate_score") or 0.0),
                float(item.get("time_start") or 0.0),
            )
        )
        items = items[:limit]
        await self.attach_episode_review_fields(items)
        return {"items": items}

    async def merge_episode(self, *, episode_id: str, absorbed_id: str) -> dict[str, Any]:
        if absorbed_id == episode_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=memory_t(
                    "memory.errors.same_episode_merge", "Cannot merge an episode into itself"
                ),
            )

        await self._get_episode_or_404(episode_id)
        await self._get_episode_or_404(absorbed_id)
        merged = await self._memory.l2.merge_episodes(
            survivor_id=episode_id,
            absorbed_id=absorbed_id,
        )
        if merged is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=memory_t("memory.errors.episode_not_found", "Episode not found"),
            )
        event_memberships = await self._memory.l2.list_episode_events(episode_id=episode_id)
        episode_summary = await self.try_regenerate_episode_summary(
            episode=merged,
            event_memberships=event_memberships,
        )
        return await self.build_episode_review_response(
            episode=merged,
            event_memberships=event_memberships,
            episode_summary=episode_summary,
        )

    async def preview_episode_split(
        self, *, episode_id: str, break_after_event_id: str
    ) -> dict[str, Any]:
        preview = await self.build_episode_split_preview(
            episode_id=episode_id,
            break_after_event_id=break_after_event_id,
        )
        return {
            "left": _public_split_side(preview["left"]),
            "right": _public_split_side(preview["right"]),
        }

    async def split_episode(self, *, episode_id: str, break_after_event_id: str) -> dict[str, Any]:
        preview = await self.build_episode_split_preview(
            episode_id=episode_id,
            break_after_event_id=break_after_event_id,
        )
        split_token = uuid.uuid4().hex[:8]
        left_id = f"{episode_id}_split_{split_token}_a"
        right_id = f"{episode_id}_split_{split_token}_b"
        result = await self._memory.l2.split_episode(
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
            self._memory.l2.list_episode_events(episode_id=str(left_episode["episode_id"])),
            self._memory.l2.list_episode_events(episode_id=str(right_episode["episode_id"])),
        )
        left_summary, right_summary = await asyncio.gather(
            self.try_regenerate_episode_summary(
                episode=left_episode,
                event_memberships=left_memberships,
            ),
            self.try_regenerate_episode_summary(
                episode=right_episode,
                event_memberships=right_memberships,
            ),
        )
        left_response, right_response = await asyncio.gather(
            self.build_episode_review_response(
                episode=left_episode,
                event_memberships=left_memberships,
                episode_summary=left_summary,
            ),
            self.build_episode_review_response(
                episode=right_episode,
                event_memberships=right_memberships,
                episode_summary=right_summary,
            ),
        )
        return {
            "source_episode_id": episode_id,
            "items": [left_response, right_response],
        }

    async def attach_episode_review_fields(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        l3_store = get_unified_layer(self._memory, "l3")
        for item in items:
            episode_summary = None
            episode_id = str(item.get("episode_id") or "").strip()
            if l3_store is not None and episode_id:
                episode_summary = serialize_episodic_summary(
                    await l3_store.get_episodic_summary_by_episode_id(episode_id)
                )
            item["episode_summary"] = episode_summary
            item.update(build_episode_display_fields(item, episode_summary))
        await attach_episode_entity_previews(self._memory, items)
        return items

    async def serialize_episode_event_previews(
        self,
        event_memberships: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return await build_episode_event_previews(self._memory, event_memberships)

    async def regenerate_episode_summary(
        self,
        *,
        episode: dict[str, Any],
        event_memberships: list[dict[str, Any]],
    ) -> dict[str, Any]:
        l1_store = get_unified_layer(self._memory, "l1")
        l3_store = get_unified_layer(self._memory, "l3")
        if l1_store is None or l3_store is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=memory_t(
                    "memory.errors.summary_store_uninitialized", "Summary store not initialized"
                ),
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
            l2_store=self._memory.l2,
            episode=episode,
            episode_event_ids=event_ids,
        )
        episode_summary = serialize_episodic_summary(summary)
        if episode_summary is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=memory_t(
                    "memory.errors.episode_summary_generation_failed",
                    "Episode summary generation failed",
                ),
            )
        updated = await self._memory.l2.update_episode(
            episode_id=str(episode.get("episode_id") or ""),
            expected_status="active",
            label=episode_summary["label"],
            summary=episode_summary["content"],
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=memory_t("memory.errors.episode_not_found", "Episode not found"),
            )
        await self._memory.l2.index_episode_fts(
            episode_id=str(episode.get("episode_id") or ""),
            summary=episode_summary["content"],
            label=episode_summary["label"],
            user_label=str(episode.get("user_label") or ""),
        )
        current = await self._memory.l2.get_episode(episode_id=str(episode.get("episode_id") or ""))
        if current is None or str(current.get("status") or "") != "active":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=memory_t("memory.errors.episode_not_found", "Episode not found"),
            )
        return episode_summary

    async def build_episode_review_response(
        self,
        *,
        episode: dict[str, Any],
        event_memberships: list[dict[str, Any]],
        episode_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        episode = dict(episode)
        await attach_episode_entity_previews(self._memory, [episode])
        if episode_summary is None:
            l3_store = get_unified_layer(self._memory, "l3")
            if l3_store is not None:
                episode_summary = serialize_episodic_summary(
                    await l3_store.get_episodic_summary_by_episode_id(
                        str(episode.get("episode_id") or "")
                    )
                )
        display_fields = build_episode_display_fields(episode, episode_summary)
        events = await self.serialize_episode_event_previews(event_memberships)
        inferred = await self._memory.l2.list_assertions_for_episode(
            episode_id=str(episode.get("episode_id") or "")
        )
        return {
            **episode,
            **display_fields,
            "episode_summary": episode_summary,
            "events": events,
            "inferred": [_serialize_episode_inference(item) for item in inferred],
        }

    async def list_event_candidate_previews(
        self,
        *,
        episode: dict[str, Any],
        current_memberships: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        l1_store = get_unified_layer(self._memory, "l1")
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
        previews.sort(
            key=lambda item: (
                -float(item.get("candidate_score") or 0.0),
                float(item.get("timestamp") or 0.0),
            )
        )
        return previews[:limit]

    async def try_regenerate_episode_summary(
        self,
        *,
        episode: dict[str, Any],
        event_memberships: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if (
            get_unified_layer(self._memory, "l1") is None
            or get_unified_layer(self._memory, "l3") is None
        ):
            return None
        try:
            return await self.regenerate_episode_summary(
                episode=episode,
                event_memberships=event_memberships,
            )
        except Exception:
            return None

    async def build_episode_split_preview(
        self,
        *,
        episode_id: str,
        break_after_event_id: str,
    ) -> dict[str, Any]:
        episode = await self._get_episode_or_404(episode_id)
        memberships = await self._memory.l2.list_episode_events(episode_id=episode_id)
        events = await self.serialize_episode_event_previews(memberships)
        if len(events) < 2:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=memory_t(
                    "memory.errors.episode_too_few_events", "Episode would have too few events"
                ),
            )

        event_ids = [str(event.get("event_id") or "") for event in events]
        try:
            break_index = event_ids.index(break_after_event_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=memory_t(
                    "memory.errors.invalid_episode_split_breakpoint", "Invalid split breakpoint"
                ),
            ) from exc
        if break_index >= len(events) - 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=memory_t(
                    "memory.errors.invalid_episode_split_breakpoint", "Invalid split breakpoint"
                ),
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

    async def _refresh_after_episode_event_change(self, episode_id: str) -> dict[str, Any]:
        updated_memberships = await self._memory.l2.list_episode_events(episode_id=episode_id)
        updated_episode = await self._refresh_episode_after_membership_change(
            episode_id=episode_id,
            event_memberships=updated_memberships,
        )
        episode_summary = await self.try_regenerate_episode_summary(
            episode=updated_episode,
            event_memberships=updated_memberships,
        )
        return await self.build_episode_review_response(
            episode=updated_episode,
            event_memberships=updated_memberships,
            episode_summary=episode_summary,
        )

    async def _refresh_episode_after_membership_change(
        self,
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
        events = await fetch_l1_events_by_ids(self._memory, event_ids)
        timestamps = [
            float(event.get("timestamp"))
            for event in events
            if isinstance(event.get("timestamp"), (int, float))
        ]
        if timestamps:
            updates["time_start"] = min(timestamps)
            updates["time_end"] = max(timestamps)
        updated = await self._memory.l2.update_episode(
            episode_id=episode_id,
            expected_status="active",
            **updates,
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=memory_t("memory.errors.episode_not_found", "Episode not found"),
            )
        return await self._get_episode_or_404(episode_id)

    async def _get_episode_or_404(self, episode_id: str) -> dict[str, Any]:
        episode = await self._memory.l2.get_episode(episode_id=episode_id)
        if episode is None or str(episode.get("status") or "") != "active":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=memory_t("memory.errors.episode_not_found", "Episode not found"),
            )
        return episode


async def reconsolidate_episode_reviews(unified_memory: Any) -> dict[str, Any]:
    """Run manual L2 episode and experience consolidation for the API surface."""
    lock_repository = await _acquire_l2_consolidation_lock()
    try:
        from magi.memory.l2.episode_formation import consolidate_episodes
        from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
        from magi.memory.l2.experiences.summary_generation import (
            generate_missing_experience_summaries,
        )

        stats = await consolidate_episodes(unified_memory.l2)

        summaries_generated = 0
        summary_errors: list[str] = []
        experience_summaries_generated = 0
        experience_summary_errors: list[str] = []

        if unified_memory.l3 is not None and unified_memory.l1 is not None:
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

        l2_cfg = get_config().agent.memory.l2
        selector = build_experience_seed_selector(
            scenario_llm_pool=scenario_llm_pool_from_unified_memory(unified_memory),
            enabled=bool(l2_cfg.experience_seed_llm_selection_enabled),
            timeout_seconds=float(l2_cfg.experience_seed_llm_timeout_seconds),
        )
        promotion_kwargs: dict[str, Any] = {}
        if selector is not None:
            promotion_kwargs["selector"] = selector
        experience_stats = await promote_experiences_from_episodes(
            unified_memory.l2,
            **promotion_kwargs,
        )
        if unified_memory.l3 is not None and unified_memory.l1 is not None:
            experience_summary_result = await generate_missing_experience_summaries(
                l1_store=unified_memory.l1,
                l2_store=unified_memory.l2,
                l3_store=unified_memory.l3,
            )
            experience_summaries_generated = int(experience_summary_result.get("generated") or 0)
            experience_summary_errors = list(experience_summary_result.get("errors") or [])

        response = {
            "promoted": stats.promoted,
            "standouts": stats.standouts,
            "merged": stats.merged,
            "invalidated": stats.invalidated,
            "summaries_generated": summaries_generated,
            "summary_errors": summary_errors,
            "experience_candidates": experience_stats.candidates,
            "experiences_promoted": experience_stats.promoted,
            "experience_duplicates": experience_stats.skipped_duplicates,
            "experience_rejected": experience_stats.rejected,
            "experience_summaries_generated": experience_summaries_generated,
            "experience_summary_errors": experience_summary_errors,
        }
    except asyncio.CancelledError:
        await _record_l2_consolidation_lock_failure(
            lock_repository,
            error="manual_reconsolidate_cancelled",
        )
        raise
    except Exception as exc:
        await _record_l2_consolidation_lock_failure(lock_repository, error=str(exc))
        raise

    await _record_l2_consolidation_lock_success(lock_repository, stats=response)
    return response


def _l2_consolidation_lock_repository() -> ScheduleRepository:
    runtime_paths = get_runtime_paths()
    scheduler_db_path = getattr(
        runtime_paths,
        "scheduler_db_path",
        Path(runtime_paths.base_dir) / "runtime" / "scheduler.db",
    )
    return ScheduleRepository(scheduler_db_path)


async def _acquire_l2_consolidation_lock() -> ScheduleRepository:
    repository = _l2_consolidation_lock_repository()
    await repository.initialize()
    acquired = await repository.acquire_target_lock(
        ScheduledTargetType.MEMORY_L2_CONSOLIDATE,
        TARGET_KEY_L2_CONSOLIDATE,
    )
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=memory_t(
                "memory.errors.l2_consolidation_busy",
                "L2 consolidation is already running",
            ),
        )
    return repository


async def _record_l2_consolidation_lock_success(
    repository: ScheduleRepository,
    *,
    stats: dict[str, Any],
) -> None:
    await repository.record_target_success(
        ScheduledTargetType.MEMORY_L2_CONSOLIDATE,
        TARGET_KEY_L2_CONSOLIDATE,
        result=ScheduledExecutionResult(
            success=True,
            message="manual_reconsolidate_ok",
            stats=stats,
        ),
        scheduler_job_id=SCHEDULE_ID_L2_CONSOLIDATE,
    )


async def _record_l2_consolidation_lock_failure(
    repository: ScheduleRepository,
    *,
    error: str,
) -> None:
    await repository.record_target_failure(
        ScheduledTargetType.MEMORY_L2_CONSOLIDATE,
        TARGET_KEY_L2_CONSOLIDATE,
        error=error,
        scheduler_job_id=SCHEDULE_ID_L2_CONSOLIDATE,
    )


def _serialize_episode_inference(assertion: dict[str, Any]) -> dict[str, Any]:
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
