"""GET /api/memory/portrait/self for the product-facing self portrait."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Query

from ....memory.provider import get_unified_memory
from ....user_profile.models import UserPortraitProjection
from ....user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from ....user_profile.portrait_projection_freshness import portrait_projection_is_stale
from ....user_profile.portrait_projection_repository import UserPortraitProjectionRepository
from ....user_profile.portrait_signal_policy import PORTRAIT_WORLD_GROUP_IDS
from ....user_profile.projection_repository import UserProfileProjectionRepository

logger = logging.getLogger(__name__)

_profile_repo_override: Any = None
_portrait_repo_override: Any = None
_l2_override: Any = None


@contextmanager
def override_dependencies_for_test(
    *,
    profile_repo: Any = None,
    portrait_repo: Any = None,
    l2: Any = None,
):
    """Temporarily replace portrait route dependencies in integration tests."""
    global _profile_repo_override, _portrait_repo_override, _l2_override
    _profile_repo_override = profile_repo
    _portrait_repo_override = portrait_repo
    _l2_override = l2
    try:
        yield
    finally:
        _profile_repo_override = None
        _portrait_repo_override = None
        _l2_override = None


def build_router() -> APIRouter:
    """Build the product-facing portrait router."""
    router = APIRouter()

    @router.get("/portrait/self")
    async def get_self_portrait(
        user_id: str = Query(..., min_length=1),
    ) -> dict[str, Any]:
        return await _get_self_portrait(user_id)

    return router


async def _get_self_portrait(user_id: str) -> dict[str, Any]:
    l2 = _resolve_l2()
    profile_projection = await _load_profile_projection(user_id)
    portrait_projection, rebuild_failed = await _load_or_build_portrait_projection(
        user_id=user_id,
        l2=l2,
        profile_projection=profile_projection,
    )
    return _portrait_payload(
        portrait_projection,
        user_id=user_id,
        rebuild_failed=rebuild_failed,
    )


async def _load_or_build_portrait_projection(
    *,
    user_id: str,
    l2: Any,
    profile_projection: Any,
) -> tuple[UserPortraitProjection | None, bool]:
    portrait_repo = _resolve_portrait_repo()
    cached = await _load_portrait_projection(portrait_repo, user_id)
    if cached is not None:
        try:
            is_stale = await portrait_projection_is_stale(
                cached,
                user_id=user_id,
                l2_store=l2,
                profile_projection=profile_projection,
            )
        except Exception as exc:
            logger.debug("self portrait: freshness check failed: %s", exc)
            is_stale = False
        if not is_stale:
            return cached, False

    rebuilt = await _build_portrait_projection(
        user_id=user_id,
        l2=l2,
        profile_projection=profile_projection,
    )
    if rebuilt is None:
        return None, True
    if portrait_repo is None:
        return rebuilt, False
    try:
        return await portrait_repo.upsert(rebuilt), False
    except Exception as exc:
        logger.debug("self portrait: projection persistence failed: %s", exc)
        return rebuilt, False


async def _load_profile_projection(user_id: str) -> Any:
    profile_repo = _resolve_profile_repo()
    if profile_repo is None:
        return None
    try:
        return await profile_repo.get(user_id)
    except Exception as exc:
        logger.debug("self portrait: profile lookup failed: %s", exc)
        return None


async def _load_portrait_projection(
    portrait_repo: Any,
    user_id: str,
) -> UserPortraitProjection | None:
    if portrait_repo is None:
        return None
    try:
        return await portrait_repo.get(user_id)
    except Exception as exc:
        logger.debug("self portrait: portrait projection lookup failed: %s", exc)
        return None


async def _build_portrait_projection(
    *,
    user_id: str,
    l2: Any,
    profile_projection: Any,
) -> UserPortraitProjection | None:
    try:
        return await UserPortraitProjectionBuilder(
            l2,
            profile_projection=profile_projection,
        ).build(user_id)
    except Exception as exc:
        logger.debug("self portrait: projection build failed: %s", exc)
        return None


def _portrait_payload(
    projection: UserPortraitProjection | None,
    *,
    user_id: str,
    rebuild_failed: bool = False,
) -> dict[str, Any]:
    if projection is None:
        projection = UserPortraitProjection(
            user_id=user_id,
            entity_id=f"user:{user_id}",
            world=_empty_world(),
            review={"items": []},
            recent={"items": []},
            generated_at=time.time(),
        )
    self_view = {
        "world": projection.world or _empty_world(),
        "review": projection.review or {"items": []},
        "recent": projection.recent or {"items": []},
    }
    is_cold_start = not rebuild_failed and not _projection_has_content(projection)
    return {
        "generated_at": projection.generated_at or time.time(),
        "self_view": self_view,
        "is_cold_start": is_cold_start,
        "cold_start_line": None,
        "cold_start_reason": "no_understanding" if is_cold_start else None,
        "is_stale": rebuild_failed,
    }


def _projection_has_content(projection: UserPortraitProjection) -> bool:
    world = projection.world or {}
    review = projection.review or {}
    recent = projection.recent or {}
    if int(world.get("total_count") or 0) > 0:
        return True
    return bool((review.get("items") or []) or (recent.get("items") or []))


def _empty_world() -> dict[str, Any]:
    return {
        "total_count": 0,
        "groups": [
            {"id": group_id, "summary": "", "items": []}
            for group_id in PORTRAIT_WORLD_GROUP_IDS
        ],
    }


def _resolve_profile_repo() -> Any:
    if _profile_repo_override is not None:
        return _profile_repo_override
    db_path = _memory_db_path()
    return UserProfileProjectionRepository(db_path) if db_path else None


def _resolve_portrait_repo() -> Any:
    if _portrait_repo_override is not None:
        return _portrait_repo_override
    db_path = _memory_db_path()
    return UserPortraitProjectionRepository(db_path) if db_path else None


def _resolve_l2() -> Any:
    if _l2_override is not None:
        return _l2_override
    try:
        unified = get_unified_memory()
    except Exception:
        return None
    return getattr(unified, "l2", None)


def _memory_db_path() -> str:
    try:
        unified = get_unified_memory()
    except Exception:
        return ""
    return str(getattr(getattr(unified, "l2", None), "db_path", "") or "")


__all__ = ["build_router", "override_dependencies_for_test"]
