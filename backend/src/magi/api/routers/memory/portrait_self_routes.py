"""GET /api/memory/portrait/self for the product-facing self portrait."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Query

from ....core.logger import get_logger
from ....memory.provider import get_unified_memory
from ....user_profile.models import UserPortraitProjection
from ....user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from ....user_profile.portrait_projection_freshness import portrait_projection_is_stale
from ....user_profile.portrait_projection_repository import UserPortraitProjectionRepository
from ....user_profile.portrait_signal_policy import PORTRAIT_WORLD_GROUP_IDS
from ....user_profile.projection_builder import UserProfileProjectionBuilder
from ....user_profile.projection_freshness import profile_projection_is_stale
from ....user_profile.projection_repository import UserProfileProjectionRepository
from ....user_profile.query_service import UserProfileQueryService

logger = get_logger(__name__)

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
    profile_projection, profile_unavailable = await _load_profile_projection(
        user_id,
        l2=l2,
    )
    portrait_projection, rebuild_failed = await _load_or_build_portrait_projection(
        user_id=user_id,
        l2=l2,
        profile_projection=profile_projection,
        input_unavailable=profile_unavailable,
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
    input_unavailable: bool = False,
) -> tuple[UserPortraitProjection | None, bool]:
    portrait_repo = _resolve_portrait_repo()
    cached = await _load_portrait_projection(portrait_repo, user_id)
    if input_unavailable:
        return cached, True
    if cached is not None:
        try:
            is_stale = await portrait_projection_is_stale(
                cached,
                user_id=user_id,
                l2_store=l2,
                profile_projection=profile_projection,
            )
        except Exception as exc:
            _log_portrait_failure(
                user_id=user_id,
                stage="freshness",
                error=exc,
                cached_kept=True,
            )
            return cached, True
        if not is_stale:
            return cached, False

    rebuilt = await _build_portrait_projection(
        user_id=user_id,
        l2=l2,
        profile_projection=profile_projection,
        cached_kept=cached is not None,
    )
    if rebuilt is None:
        return cached, True
    if portrait_repo is None:
        return rebuilt, False
    try:
        return await portrait_repo.upsert(rebuilt), False
    except Exception as exc:
        _log_portrait_failure(
            user_id=user_id,
            stage="persist",
            error=exc,
            cached_kept=cached is not None,
        )
        return rebuilt, False


async def _load_profile_projection(user_id: str, *, l2: Any) -> tuple[Any, bool]:
    profile_repo = _resolve_profile_repo()
    if profile_repo is None:
        return None, l2 is not None
    if l2 is None:
        try:
            return await profile_repo.get(user_id), True
        except Exception as exc:
            _log_portrait_failure(
                user_id=user_id,
                stage="profile_lookup",
                error=exc,
                cached_kept=False,
            )
            return None, True
    try:
        service = UserProfileQueryService(
            repository=profile_repo,
            builder=UserProfileProjectionBuilder(l2),
        )
        projection = await service.get_current_profile(user_id)
        is_stale = await profile_projection_is_stale(
            projection,
            user_id=user_id,
            l2_store=l2,
        )
        return projection, is_stale
    except Exception as exc:
        try:
            cached = await profile_repo.get(user_id)
        except Exception:
            cached = None
        _log_portrait_failure(
            user_id=user_id,
            stage="profile_freshness",
            error=exc,
            cached_kept=cached is not None,
        )
        return cached, True


async def _load_portrait_projection(
    portrait_repo: Any,
    user_id: str,
) -> UserPortraitProjection | None:
    if portrait_repo is None:
        return None
    try:
        return await portrait_repo.get(user_id)
    except Exception as exc:
        _log_portrait_failure(
            user_id=user_id,
            stage="cache_lookup",
            error=exc,
            cached_kept=False,
        )
        return None


async def _build_portrait_projection(
    *,
    user_id: str,
    l2: Any,
    profile_projection: Any,
    cached_kept: bool,
) -> UserPortraitProjection | None:
    try:
        return await UserPortraitProjectionBuilder(
            l2,
            profile_projection=profile_projection,
        ).build(user_id)
    except Exception as exc:
        _log_portrait_failure(
            user_id=user_id,
            stage="rebuild",
            error=exc,
            cached_kept=cached_kept,
        )
        return None


def _log_portrait_failure(
    *,
    user_id: str,
    stage: str,
    error: Exception,
    cached_kept: bool,
) -> None:
    logger.error(
        "User portrait projection input failed",
        user_id=user_id,
        projection_kind="portrait",
        stage=stage,
        cached_kept=cached_kept,
        error_type=type(error).__name__,
    )


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
