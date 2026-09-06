"""Read-only diagnostics with explicit population and lifetime boundaries."""

from typing import Any

from fastapi import HTTPException, Query

from magi.user_profile.projection_builder import UserProfileProjectionBuilder
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from .dependencies import _resolve_unified_memory
from .router import memory_router


@memory_router.get("/quality")
async def get_memory_quality(user_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    unified = _resolve_unified_memory()
    if unified is None or unified.l2 is None or unified.l1 is None:
        raise HTTPException(status_code=503, detail="Memory diagnostics are unavailable")
    async with unified.memory_operation_guard():
        counts = await unified.l2.get_claim_quality_counts(user_id=user_id)
        profile = await UserProfileProjectionBuilder(unified.l2).build(user_id)
        portrait = await UserPortraitProjectionBuilder(
            unified.l2, profile_projection=profile
        ).build(user_id)
        items = [
            item for group in portrait.world.get("groups", []) for item in group.get("items", [])
        ]
        items += portrait.recent.get("items", [])
        visible_ids = {item["assertion_id"] for item in items if item.get("assertion_id")}
        return {
            "runtime": {"scope": "process_attempts", "counts": unified.get_l2_pipeline_stats()},
            "stored": {
                "scope": "active_store_records",
                "l1_events": await unified.l1.count_events(),
                "projection_backlog": await unified.l2.get_projection_backlog_stats(),
            },
            "user": {
                "user_id": user_id,
                **counts,
                "profile_visible_assertions": len(visible_ids),
                "profile_visible_items": len(items),
                "profile_review_items": len(portrait.review.get("items", [])),
            },
        }
