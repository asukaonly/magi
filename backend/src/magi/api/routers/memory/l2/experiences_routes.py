"""L2 experience API routes."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, Query, UploadFile, status

from magi.core.logger import get_logger
from magi.api.services.l2_episode_review_helpers import (
    build_episode_display_fields,
    serialize_episodic_summary,
)
from magi.api.services.l2_episode_review_read_model import (
    attach_episode_entity_previews,
    fetch_l1_events_by_ids,
    get_configured_or_real_method,
    get_unified_layer,
    ordered_non_empty_strings,
    serialize_episode_event_previews,
)
from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
from magi.memory.l2.experiences.draft_creation import create_experience_from_draft
from magi.memory.l2.experiences.draft_organizer import organize_experience_draft
from magi.memory.l2.experiences.seed_discovery import discover_manual_experience_seed
from magi.memory.l3.episode_backwrite import backwrite_experience_review

from ..asset_uploads import store_uploaded_image_asset
from ..dependencies import _resolve_manual_entry_asset_store, _resolve_unified_memory
from ..helpers import memory_t
from ..router import memory_router
from ..schemas import (
    ExperienceAnnotationRequest,
    ExperienceDraftOrganizeRequest,
    ExperienceDraftUpdateRequest,
    ExperienceSeedCreateRequest,
)

_DRAFT_EVENT_MEMBERSHIP_LIMIT = 10_000
_DRAFT_EVENT_MEMBERSHIP_CONCURRENCY = 8
logger = get_logger(__name__)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _format_anchor_label(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if ":" in text:
        text = text.split(":", 1)[1]
    return text.replace("-", " ").replace("_", " ").strip()


def _experience_seed_anchor_labels(seed: dict[str, Any], limit: int = 3) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for key in ("anchor_entity_ids", "anchor_place_ids", "anchor_topic_keys"):
        for value in seed.get(key) or []:
            label = _format_anchor_label(value)
            if label and label not in seen:
                seen.add(label)
                labels.append(label)
            if len(labels) >= limit:
                return labels
    return labels


def _experience_seed_display_fields(seed: dict[str, Any]) -> dict[str, Any]:
    title = _clean_text(seed.get("title"))
    description = _clean_text(seed.get("description"))
    labels = _experience_seed_anchor_labels(seed)
    subject = "、".join(labels[:2])
    if not title:
        title = f"可能是围绕 {subject} 的经历" if subject else "可能是一段经历"
    if not description:
        description = (
            f"这些片段在相近时间里围绕「{subject}」反复出现，Magi 觉得可以整理成一段经历。"
            if subject
            else "这些片段在相近时间里反复出现，Magi 觉得可以整理成一段经历。"
        )
    return {
        "display_title": title,
        "display_description": description,
        "display_tags": labels,
    }


async def _attach_experience_seed_display_fields(
    unified_memory: Any,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    for item in items:
        seed_id = _clean_text(item.get("seed_id"))
        evidence = (
            await unified_memory.l2.list_experience_seed_evidence(seed_id=seed_id, limit=100)
            if seed_id and hasattr(unified_memory.l2, "list_experience_seed_evidence")
            else []
        )
        item["evidence_count"] = len(evidence)
        item.update(_experience_seed_display_fields(item))
    return items


def _build_experience_display_fields(
    experience: dict[str, Any],
    experience_review: dict[str, Any] | None,
) -> dict[str, str]:
    review = experience_review or {}
    user_title = _clean_text(experience.get("user_label"))
    user_description = _clean_text(experience.get("user_note"))
    generated_title = _first_text(
        review.get("label"), experience.get("title"), experience.get("intent")
    )
    generated_description = _first_text(
        review.get("content"),
        experience.get("magi_interpretation"),
        experience.get("outcome"),
        experience.get("intent"),
    )
    display_title = (
        user_title
        or generated_title
        or _clean_text(experience.get("experience_id"))
        or "Experience"
    )
    display_description = user_description or generated_description
    if user_title or user_description:
        display_source = "user_override"
    elif generated_title or generated_description:
        display_source = "generated"
    else:
        display_source = "fallback"
    return {
        "display_title": display_title,
        "display_description": display_description,
        "display_source": display_source,
    }


async def _attach_experience_review_fields(
    unified_memory: Any,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    l3_store = get_unified_layer(unified_memory, "l3")
    for item in items:
        review = None
        experience_id = str(item.get("experience_id") or "").strip()
        if l3_store is not None and experience_id:
            get_review = get_configured_or_real_method(
                l3_store,
                "get_episodic_summary_by_experience_id",
            )
            if get_review is not None:
                review = serialize_episodic_summary(await get_review(experience_id))
        item["experience_review"] = review
        item.update(_build_experience_display_fields(item, review))
    await attach_episode_entity_previews(unified_memory, items)
    return items


async def _get_experience_or_404(unified_memory: Any, experience_id: str) -> dict[str, Any]:
    experience = await unified_memory.l2.get_experience(experience_id=experience_id)
    if experience is None or str(experience.get("status") or "") == "invalidated":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.experience_not_found", "Experience not found"),
        )
    return experience


async def _get_active_experience_or_404(
    unified_memory: Any,
    experience_id: str,
) -> dict[str, Any]:
    experience = await _get_experience_or_404(unified_memory, experience_id)
    if str(experience.get("status") or "") != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.experience_not_found", "Experience not found"),
        )
    return experience


async def _source_episode_previews(
    unified_memory: Any,
    members: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    get_episode = get_configured_or_real_method(unified_memory.l2, "get_episode")
    if get_episode is None:
        return previews
    l3_store = get_unified_layer(unified_memory, "l3")
    get_episode_summary = (
        get_configured_or_real_method(l3_store, "get_episodic_summary_by_episode_id")
        if l3_store is not None
        else None
    )
    for member in members:
        if member.get("member_type") != "episode":
            continue
        role = str(member.get("role") or "")
        if role == "excluded":
            continue
        episode_id = str(member.get("member_id") or "").strip()
        if not episode_id:
            continue
        episode = await get_episode(episode_id=episode_id)
        if episode is None or str(episode.get("status") or "") != "active":
            continue
        item = dict(episode)
        episode_summary = (
            serialize_episodic_summary(await get_episode_summary(episode_id))
            if get_episode_summary is not None
            else None
        )
        item["episode_summary"] = episode_summary
        item.update(build_episode_display_fields(item, episode_summary))
        item["membership_role"] = role
        item["membership_confidence"] = float(member.get("confidence") or 0.0)
        item["membership_added_at"] = member.get("added_at")
        previews.append(item)
    await attach_episode_entity_previews(unified_memory, previews)
    return previews


async def _experience_event_previews(
    unified_memory: Any,
    members: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    event_memberships: list[dict[str, Any]] = []
    seen: set[str] = set()
    list_episode_events = get_configured_or_real_method(
        unified_memory.l2,
        "list_episode_events",
    )
    for member in members:
        member_type = str(member.get("member_type") or "")
        member_id = str(member.get("member_id") or "").strip()
        if not member_id or str(member.get("role") or "") == "excluded":
            continue
        if member_type == "episode":
            if list_episode_events is None:
                continue
            for item in await list_episode_events(episode_id=member_id):
                event_id = str(item.get("event_id") or "").strip()
                if event_id and event_id not in seen:
                    seen.add(event_id)
                    event_memberships.append(item)
        elif member_type == "event" and member_id not in seen:
            seen.add(member_id)
            event_memberships.append(
                {
                    "episode_id": "",
                    "event_id": member_id,
                    "membership_role": str(member.get("role") or "core"),
                    "membership_confidence": float(member.get("confidence") or 0.0),
                    "added_at": member.get("added_at"),
                }
            )
    return await serialize_episode_event_previews(unified_memory, event_memberships)


async def _build_experience_review_response(
    unified_memory: Any,
    *,
    experience: dict[str, Any],
    members: list[dict[str, Any]] | None = None,
    experience_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    experience = dict(experience)
    await _attach_experience_review_fields(unified_memory, [experience])
    if experience_review is not None:
        experience["experience_review"] = experience_review
        experience.update(_build_experience_display_fields(experience, experience_review))
    if members is None:
        list_members = get_configured_or_real_method(
            unified_memory.l2,
            "list_experience_members",
        )
        members = (
            await list_members(experience_id=str(experience.get("experience_id") or ""))
            if list_members is not None
            else []
        )
    source_episodes = await _source_episode_previews(unified_memory, members)
    events = await _experience_event_previews(unified_memory, members)
    return {
        **experience,
        "source_episodes": source_episodes,
        "events": events,
        "key_events": [],
    }


async def _episode_ids_from_seed_request(
    unified_memory: Any,
    body: ExperienceSeedCreateRequest,
) -> list[str]:
    episode_ids = ordered_non_empty_strings(body.episode_ids)
    if body.event_ids:
        find_episode = get_configured_or_real_method(
            unified_memory.l2,
            "find_episode_for_event",
        )
        if find_episode is not None:
            for event_id in body.event_ids:
                episode = await find_episode(event_id=event_id)
                episode_id = _clean_text((episode or {}).get("episode_id"))
                if episode_id:
                    episode_ids.append(episode_id)
    return ordered_non_empty_strings(episode_ids)


def _require_l2_memory() -> Any:
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    return unified_memory


def _experience_seed_extra_evidence(
    *,
    episode_ids: list[str],
    event_ids: list[str],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = [
        {
            "ref_type": "episode",
            "ref_id": episode_id,
            "role": "support",
            "confidence": 0.8,
        }
        for episode_id in episode_ids[1:]
    ]
    evidence.extend(
        {
            "ref_type": "event",
            "ref_id": event_id,
            "role": "support",
            "confidence": 0.7,
        }
        for event_id in event_ids
    )
    return evidence


async def _create_manual_experience_seed(
    unified_memory: Any,
    *,
    body: ExperienceSeedCreateRequest,
    episode_ids: list[str],
) -> str:
    return await discover_manual_experience_seed(
        unified_memory.l2,
        episode_id=episode_ids[0],
        title=_clean_text(body.title_hint) or None,
    )


async def _validate_manual_seed_sources(
    unified_memory: Any,
    *,
    episode_ids: list[str],
    event_ids: list[str],
) -> None:
    for episode_id in episode_ids:
        episode = await unified_memory.l2.get_episode(episode_id=episode_id)
        if episode is None or str(episode.get("status") or "") != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=memory_t(
                    "memory.errors.experience_seed_not_promotable",
                    "Experience seed evidence is no longer active",
                ),
            )
    if event_ids:
        events = await fetch_l1_events_by_ids(unified_memory, event_ids)
        active_ids = {str(event.get("event_id") or "") for event in events}
        if any(event_id not in active_ids for event_id in event_ids):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=memory_t(
                    "memory.errors.experience_seed_not_promotable",
                    "Experience seed evidence is no longer active",
                ),
            )


async def _add_manual_experience_seed_evidence(
    unified_memory: Any,
    *,
    seed_id: str,
    episode_ids: list[str],
    event_ids: list[str],
) -> None:
    extra_evidence = _experience_seed_extra_evidence(
        episode_ids=episode_ids,
        event_ids=event_ids,
    )
    if extra_evidence:
        await unified_memory.l2.add_experience_seed_evidence(
            seed_id=seed_id,
            evidence=extra_evidence,
        )


async def _promote_seed_for_create_response(
    unified_memory: Any,
    *,
    seed_id: str,
    promote_now: bool,
) -> tuple[str | None, dict[str, Any] | None]:
    if not promote_now:
        return None, None
    stats = await promote_experiences_from_episodes(
        unified_memory.l2,
        target_seed_id=seed_id,
    )
    if not stats.promoted_experience_ids:
        return None, None
    experience_id = str(stats.promoted_experience_ids[0])
    response = await _build_promoted_experience_response(
        unified_memory,
        experience_id=experience_id,
    )
    if response is None:
        return None, None
    return experience_id, response


async def _build_promoted_experience_response(
    unified_memory: Any,
    *,
    experience_id: str,
) -> dict[str, Any] | None:
    try:
        experience = await _get_active_experience_or_404(
            unified_memory,
            experience_id,
        )
    except HTTPException:
        return None
    members = await unified_memory.l2.list_experience_members(
        experience_id=experience_id,
    )
    return await _build_experience_review_response(
        unified_memory,
        experience=experience,
        members=members,
    )


@memory_router.post("/l2/experience-drafts/organize")
async def organize_experience_draft_route(
    body: ExperienceDraftOrganizeRequest,
) -> dict[str, Any]:
    """Organize a natural-language request into a persisted draft."""
    unified_memory = _require_l2_memory()
    if not unified_memory.l1:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l1_store_uninitialized", "L1 store not initialized"),
        )
    return await organize_experience_draft(
        unified_memory,
        query_text=body.query_text,
        time_start=body.time_start,
        time_end=body.time_end,
    )


@memory_router.get("/l2/experience-drafts")
async def list_experience_drafts_route(
    draft_status: str = Query(default="editing", alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List resumable experience drafts."""
    unified_memory = _require_l2_memory()
    items = await unified_memory.l2.list_experience_drafts(
        status=draft_status,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": len(items), "limit": limit, "offset": offset}


def _coerce_draft_event_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


async def _hydrate_experience_draft_event_counts(
    unified_memory: Any,
    draft: dict[str, Any],
) -> dict[str, Any]:
    l2_store = get_unified_layer(unified_memory, "l2")
    list_episode_events = get_configured_or_real_method(
        l2_store,
        "list_episode_events",
    )
    update_experience_draft = get_configured_or_real_method(
        l2_store,
        "update_experience_draft",
    )
    get_experience_draft = get_configured_or_real_method(
        l2_store,
        "get_experience_draft",
    )
    draft_id = _clean_text(draft.get("draft_id"))

    missing_episode_ids: set[str] = set()
    for chapter in draft.get("chapters") or []:
        if (
            isinstance(chapter, Mapping)
            and _coerce_draft_event_count(chapter.get("event_count")) is None
        ):
            missing_episode_ids.update(ordered_non_empty_strings(chapter.get("episode_ids")))
    for key in ("possible_evidence", "excluded_evidence"):
        for evidence in draft.get(key) or []:
            if not isinstance(evidence, Mapping):
                continue
            event_count = _coerce_draft_event_count(evidence.get("event_count"))
            restore_chapter = evidence.get("restore_chapter")
            if isinstance(restore_chapter, Mapping):
                restored_count = _coerce_draft_event_count(restore_chapter.get("event_count"))
                if event_count is None and restored_count is None:
                    missing_episode_ids.update(
                        ordered_non_empty_strings(restore_chapter.get("episode_ids")),
                    )
            elif event_count is None and evidence.get("ref_type") == "episode":
                ref_id = _clean_text(evidence.get("ref_id"))
                if ref_id:
                    missing_episode_ids.add(ref_id)

    membership_semaphore = asyncio.Semaphore(_DRAFT_EVENT_MEMBERSHIP_CONCURRENCY)

    async def load_membership_event_ids(
        episode_id: str,
    ) -> tuple[str, set[str] | None]:
        try:
            async with membership_semaphore:
                memberships = await list_episode_events(
                    episode_id=episode_id,
                    limit=_DRAFT_EVENT_MEMBERSHIP_LIMIT,
                )
        except Exception as exc:
            logger.warning(
                "experience_draft_membership_read_failed",
                draft_id=draft_id,
                episode_id=episode_id,
                error=str(exc),
            )
            return episode_id, None
        return episode_id, {
            event_id
            for membership in memberships
            if isinstance(membership, Mapping)
            for event_id in ordered_non_empty_strings([membership.get("event_id")])
        }

    episode_event_ids = (
        dict(
            await asyncio.gather(
                *(
                    load_membership_event_ids(episode_id)
                    for episode_id in sorted(missing_episode_ids)
                )
            )
        )
        if list_episode_events is not None
        else {}
    )

    def count_evidence(episode_ids: Any, direct_event_ids: Any) -> int | None:
        normalized_episode_ids = ordered_non_empty_strings(episode_ids)
        distinct_ids = set(ordered_non_empty_strings(direct_event_ids))
        if normalized_episode_ids and list_episode_events is None:
            return None
        for episode_id in normalized_episode_ids:
            membership_ids = episode_event_ids.get(episode_id)
            if membership_ids is None:
                return None
            distinct_ids.update(membership_ids)
        return len(distinct_ids)

    def hydrate_chapter(chapter: Any) -> Any:
        if not isinstance(chapter, Mapping):
            return chapter
        hydrated = dict(chapter)
        event_count = _coerce_draft_event_count(hydrated.get("event_count"))
        if event_count is None:
            event_count = count_evidence(
                hydrated.get("episode_ids"),
                hydrated.get("event_ids"),
            )
        if event_count is None:
            hydrated.pop("event_count", None)
        else:
            hydrated["event_count"] = event_count
        return hydrated

    def hydrate_evidence(evidence: Any) -> Any:
        if not isinstance(evidence, Mapping):
            return evidence
        hydrated = dict(evidence)
        event_count = _coerce_draft_event_count(hydrated.get("event_count"))
        restore_chapter = hydrated.get("restore_chapter")
        if isinstance(restore_chapter, Mapping):
            restored = dict(restore_chapter)
            restored_count = _coerce_draft_event_count(restored.get("event_count"))
            if restored_count is None:
                restored_count = event_count
            if restored_count is None:
                restored_count = count_evidence(
                    restored.get("episode_ids"),
                    restored.get("event_ids"),
                )
            if restored_count is None:
                restored.pop("event_count", None)
            else:
                restored["event_count"] = restored_count
            hydrated["restore_chapter"] = restored
            if event_count is None:
                event_count = restored_count
        if event_count is None:
            ref_id = _clean_text(hydrated.get("ref_id"))
            if hydrated.get("ref_type") == "episode" and ref_id:
                event_count = count_evidence([ref_id], [])
            elif hydrated.get("ref_type") == "event" and ref_id:
                event_count = 1
        if event_count is None:
            hydrated.pop("event_count", None)
        else:
            hydrated["event_count"] = event_count
        return hydrated

    hydrated_draft = dict(draft)
    changed_fields: dict[str, Any] = {}
    if "chapters" in draft:
        chapters = [hydrate_chapter(chapter) for chapter in draft.get("chapters") or []]
        hydrated_draft["chapters"] = chapters
        if chapters != draft.get("chapters"):
            changed_fields["chapters"] = chapters
    for key in ("possible_evidence", "excluded_evidence"):
        if key not in draft:
            continue
        evidence_items = [hydrate_evidence(evidence) for evidence in draft.get(key) or []]
        hydrated_draft[key] = evidence_items
        if evidence_items != draft.get(key):
            changed_fields[key] = evidence_items
    initial_updated_at = draft.get("updated_at")
    if (
        changed_fields
        and draft_id
        and initial_updated_at is not None
        and get_experience_draft is not None
        and update_experience_draft is not None
    ):
        try:
            latest_draft = await get_experience_draft(draft_id=draft_id)
            if latest_draft is not None and latest_draft.get("updated_at") == initial_updated_at:
                await update_experience_draft(
                    draft_id=draft_id,
                    expected_updated_at=float(initial_updated_at),
                    **changed_fields,
                )
        except Exception as exc:
            logger.warning(
                "experience_draft_count_backfill_failed",
                draft_id=draft_id,
                error=str(exc),
            )
    return hydrated_draft


async def _get_experience_draft_or_404(
    unified_memory: Any,
    draft_id: str,
    *,
    hydrate_event_counts: bool = False,
) -> dict[str, Any]:
    draft = await unified_memory.l2.get_experience_draft(draft_id=draft_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t(
                "memory.errors.experience_draft_not_found", "Experience draft not found"
            ),
        )
    if hydrate_event_counts:
        return await _hydrate_experience_draft_event_counts(unified_memory, draft)
    return draft


@memory_router.get("/l2/experience-drafts/{draft_id}")
async def get_experience_draft_route(draft_id: str) -> dict[str, Any]:
    """Return one experience draft."""
    return await _get_experience_draft_or_404(
        _require_l2_memory(),
        draft_id,
        hydrate_event_counts=True,
    )


@memory_router.patch("/l2/experience-drafts/{draft_id}")
async def update_experience_draft_route(
    draft_id: str,
    body: ExperienceDraftUpdateRequest,
) -> dict[str, Any]:
    """Autosave user edits to an experience draft."""
    unified_memory = _require_l2_memory()
    await _get_experience_draft_or_404(unified_memory, draft_id)
    updates = body.model_dump(exclude_unset=True)
    if updates:
        await unified_memory.l2.update_experience_draft(draft_id=draft_id, **updates)
    return await _get_experience_draft_or_404(
        unified_memory,
        draft_id,
        hydrate_event_counts=True,
    )


@memory_router.post("/l2/experience-drafts/{draft_id}/cover")
async def upload_experience_draft_cover(draft_id: str, file: UploadFile) -> dict[str, Any]:
    """Upload and persist a user-selected cover image for an experience draft."""
    unified_memory = _require_l2_memory()
    asset_store = _resolve_manual_entry_asset_store()
    if asset_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.asset_store_uninitialized", "Asset storage not initialized"
            ),
        )

    await _get_experience_draft_or_404(unified_memory, draft_id)
    upload = await store_uploaded_image_asset(file, asset_store)
    ok = await unified_memory.l2.update_experience_draft(
        draft_id=draft_id,
        user_cover_asset_ref=upload["asset_ref"],
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t(
                "memory.errors.experience_draft_not_found", "Experience draft not found"
            ),
        )
    return await _get_experience_draft_or_404(
        unified_memory,
        draft_id,
        hydrate_event_counts=True,
    )


@memory_router.post("/l2/experience-drafts/{draft_id}/create")
async def create_experience_from_draft_route(draft_id: str) -> dict[str, Any]:
    """Create an active experience from the user-approved draft."""
    unified_memory = _require_l2_memory()
    await _get_experience_draft_or_404(unified_memory, draft_id)
    try:
        experience_id = await create_experience_from_draft(
            unified_memory.l2,
            draft_id=draft_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    experience = await unified_memory.l2.get_experience(experience_id=experience_id)
    return {
        "draft_id": draft_id,
        "experience_id": experience_id,
        "experience": experience,
    }


@memory_router.post("/l2/experience-seeds")
async def create_l2_experience_seed(body: ExperienceSeedCreateRequest):
    """Create a manual experience seed from selected episode or event evidence."""
    unified_memory = _require_l2_memory()
    episode_ids = await _episode_ids_from_seed_request(unified_memory, body)
    if not episode_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=memory_t("memory.errors.no_seed_evidence", "No seed evidence provided"),
        )

    await _validate_manual_seed_sources(
        unified_memory,
        episode_ids=episode_ids,
        event_ids=body.event_ids,
    )
    try:
        seed_id = await _create_manual_experience_seed(
            unified_memory,
            body=body,
            episode_ids=episode_ids,
        )
        await _add_manual_experience_seed_evidence(
            unified_memory,
            seed_id=seed_id,
            episode_ids=episode_ids,
            event_ids=body.event_ids,
        )
    except ValueError as exc:
        raise _experience_seed_not_promotable() from exc

    promoted_experience_id, experience_response = await _promote_seed_for_create_response(
        unified_memory,
        seed_id=seed_id,
        promote_now=body.promote_now,
    )

    seed = await unified_memory.l2.get_experience_seed(seed_id=seed_id)
    return {
        "seed_id": seed_id,
        "seed": seed,
        "promoted_experience_id": promoted_experience_id,
        "experience": experience_response,
    }


@memory_router.get("/l2/experience-seeds")
async def list_l2_experience_seeds(
    status_filter: str | None = Query(default="candidate", alias="status"),
    limit: int = Query(default=12, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List user-reviewable L2 experience candidates."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items = await unified_memory.l2.list_experience_seeds(
        status=status_filter,
        limit=None,
    )
    total = len(items)
    items = items[offset:offset + limit]
    await _attach_experience_seed_display_fields(unified_memory, items)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@memory_router.post("/l2/experience-seeds/{seed_id}/promote")
async def promote_l2_experience_seed(seed_id: str):
    """Promote one accepted experience candidate into an active experience."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    seed = await unified_memory.l2.get_experience_seed(seed_id=seed_id)
    if seed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.experience_seed_not_found", "Experience seed not found"),
        )
    seed_status = str(seed.get("status") or "").strip()
    existing_experience_id = _clean_text(seed.get("promoted_experience_id")) or None
    if existing_experience_id is not None:
        experience = await _get_experience_or_404(unified_memory, existing_experience_id)
        if seed_status != "promoted":
            raise _experience_seed_not_promotable()
        return {
            "seed_id": seed_id,
            "seed": seed,
            "promoted_experience_id": existing_experience_id,
            "experience": await _build_experience_review_response(
                unified_memory,
                experience=experience,
            ),
        }
    if seed_status not in {"candidate", "accepted"}:
        raise _experience_seed_not_promotable()
    if seed_status == "candidate":
        accepted = await unified_memory.l2.update_experience_seed(
            seed_id=seed_id,
            expected_statuses=["candidate"],
            status="accepted",
        )
        if not accepted:
            raise _experience_seed_not_promotable()
    stats = await promote_experiences_from_episodes(
        unified_memory.l2,
        target_seed_id=seed_id,
    )
    seed = await unified_memory.l2.get_experience_seed(seed_id=seed_id)
    promoted_experience_id = _clean_text((seed or {}).get("promoted_experience_id")) or None
    if promoted_experience_id is None and stats.promoted_experience_ids:
        promoted_experience_id = str(stats.promoted_experience_ids[0])
    if promoted_experience_id is None:
        raise _experience_seed_not_promotable()

    experience_response: dict[str, Any] | None = None
    if promoted_experience_id:
        experience = await _get_experience_or_404(unified_memory, promoted_experience_id)
        members = await unified_memory.l2.list_experience_members(
            experience_id=promoted_experience_id,
        )
        experience_response = await _build_experience_review_response(
            unified_memory,
            experience=experience,
            members=members,
        )
    return {
        "seed_id": seed_id,
        "seed": seed,
        "promoted_experience_id": promoted_experience_id,
        "experience": experience_response,
    }


def _experience_seed_not_promotable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=memory_t(
            "memory.errors.experience_seed_not_promotable",
            "Experience seed is no longer available for promotion",
        ),
    )


@memory_router.post("/l2/experience-seeds/{seed_id}/reject")
async def reject_l2_experience_seed(seed_id: str):
    """Dismiss one experience candidate from the review surface."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    ok = await unified_memory.l2.update_experience_seed(seed_id=seed_id, status="rejected")
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.experience_seed_not_found", "Experience seed not found"),
        )
    seed = await unified_memory.l2.get_experience_seed(seed_id=seed_id)
    return {"seed_id": seed_id, "seed": seed}


@memory_router.get("/l2/experiences")
async def list_l2_experiences(
    status_filter: str | None = Query(default=None, alias="status"),
    time_start: float | None = Query(default=None),
    time_end: float | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List product-grade L2 experiences."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    if (status_filter or "").strip().lower() == "invalidated":
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    effective_status = status_filter if status_filter is not None else "active"
    items = await unified_memory.l2.list_experiences(
        status=effective_status,
        time_start=time_start,
        time_end=time_end,
        limit=limit,
        offset=offset,
    )
    await _attach_experience_review_fields(unified_memory, items)
    return {"items": items, "total": len(items), "limit": limit, "offset": offset}


@memory_router.get("/l2/experiences/{experience_id}")
async def get_l2_experience(experience_id: str):
    """Get one L2 experience with source episode and event evidence."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    experience = await _get_experience_or_404(unified_memory, experience_id)
    members = await unified_memory.l2.list_experience_members(experience_id=experience_id)
    return await _build_experience_review_response(
        unified_memory,
        experience=experience,
        members=members,
    )


@memory_router.post("/l2/experiences/{experience_id}/cover")
async def upload_l2_experience_cover(experience_id: str, file: UploadFile):
    """Upload and persist a user-selected cover image for an experience."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    asset_store = _resolve_manual_entry_asset_store()
    if asset_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.asset_store_uninitialized", "Asset storage not initialized"
            ),
        )

    current = await _get_experience_or_404(unified_memory, experience_id)
    upload = await store_uploaded_image_asset(file, asset_store)
    ok = await unified_memory.l2.update_experience(
        experience_id=experience_id,
        expected_status=str(current.get("status") or ""),
        user_cover_asset_ref=upload["asset_ref"],
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.experience_not_found", "Experience not found"),
        )
    experience = await _get_experience_or_404(unified_memory, experience_id)
    return await _build_experience_review_response(
        unified_memory,
        experience=experience,
    )


@memory_router.patch("/l2/experiences/{experience_id}")
async def annotate_l2_experience(experience_id: str, body: ExperienceAnnotationRequest):
    """User annotation on an experience."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    updates: dict[str, Any] = {}
    if body.user_label is not None:
        updates["user_label"] = body.user_label
    if body.user_note is not None:
        updates["user_note"] = body.user_note
    if body.user_pinned is not None:
        updates["user_pinned"] = body.user_pinned
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=memory_t("memory.errors.no_fields_to_update", "No fields to update"),
        )
    current = await _get_experience_or_404(unified_memory, experience_id)
    ok = await unified_memory.l2.update_experience(
        experience_id=experience_id,
        expected_status=str(current.get("status") or ""),
        **updates,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.experience_not_found", "Experience not found"),
        )
    experience = await _get_experience_or_404(unified_memory, experience_id)
    return await _build_experience_review_response(unified_memory, experience=experience)


@memory_router.post("/l2/experiences/{experience_id}/hide")
async def hide_l2_experience(experience_id: str):
    """Hide an experience from the primary review surface."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    current = await _get_experience_or_404(unified_memory, experience_id)
    current_status = str(current.get("status") or "")
    if current_status == "hidden":
        return await _build_experience_review_response(
            unified_memory,
            experience=current,
        )
    if current_status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.experience_not_found", "Experience not found"),
        )
    ok = await unified_memory.l2.update_experience(
        experience_id=experience_id,
        expected_status="active",
        status="hidden",
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.experience_not_found", "Experience not found"),
        )
    experience = await _get_experience_or_404(unified_memory, experience_id)
    return await _build_experience_review_response(unified_memory, experience=experience)


@memory_router.post("/l2/experiences/{experience_id}/regenerate")
async def regenerate_l2_experience(experience_id: str):
    """Regenerate the L3 recap for an experience."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    l1_store = get_unified_layer(unified_memory, "l1")
    l3_store = get_unified_layer(unified_memory, "l3")
    if l1_store is None or l3_store is None or not hasattr(l3_store, "generate_experience_summary"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.summary_store_uninitialized", "Summary store not initialized"
            ),
        )
    experience = await _get_experience_or_404(unified_memory, experience_id)
    members = await unified_memory.l2.list_experience_members(experience_id=experience_id)
    generated_summary = await l3_store.generate_experience_summary(
        l1_store=l1_store,
        l2_store=unified_memory.l2,
        experience=experience,
        experience_members=members,
    )
    current = await unified_memory.l2.get_experience(experience_id=experience_id)
    if current is None or str(current.get("status") or "") != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.experience_not_found", "Experience not found"),
        )
    review = serialize_episodic_summary(generated_summary)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=memory_t(
                "memory.errors.experience_summary_generation_failed",
                "Experience summary generation failed",
            ),
        )
    await backwrite_experience_review(
        unified_memory.l2,
        experience=current,
        summary=generated_summary,
    )
    current = await _get_active_experience_or_404(unified_memory, experience_id)
    return await _build_experience_review_response(
        unified_memory,
        experience=current,
        members=members,
        experience_review=review,
    )
