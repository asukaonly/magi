"""Personal profile API routes."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status

from ...memory.provider import get_unified_memory
from ...user_profile import (
    ProfileUpdatePatch,
    UserProfileCommandService,
    UserProfileQueryService,
)
from ...user_profile.models import DEFAULT_USER_ID, UserProfileProjection
from ...user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from ...user_profile.portrait_projection_repository import UserPortraitProjectionRepository
from ...user_profile.projection_builder import UserProfileProjectionBuilder
from ...user_profile.projection_repository import UserProfileProjectionRepository

def _resolve_unified_memory():
    try:
        return get_unified_memory()
    except RuntimeError:
        return None


async def _profile_memory_operation_boundary() -> AsyncIterator[None]:
    unified_memory = _resolve_unified_memory()
    if unified_memory is None:
        yield
        return
    async with unified_memory.memory_operation_guard():
        yield


profile_router = APIRouter(
    dependencies=[Depends(_profile_memory_operation_boundary)]
)


def _build_services():
    unified_memory = _resolve_unified_memory()
    l2 = getattr(unified_memory, "l2", None) if unified_memory is not None else None
    if unified_memory is None or l2 is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory profile service is not initialized",
        )
    db_path = str(getattr(l2, "db_path", "") or "")
    if not db_path:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory profile database is not initialized",
        )
    repository = UserProfileProjectionRepository(db_path)
    builder = UserProfileProjectionBuilder(l2)
    portrait_repository = UserPortraitProjectionRepository(db_path)
    portrait_builder = UserPortraitProjectionBuilder(l2)
    query_service = UserProfileQueryService(repository=repository, builder=builder)
    command_service = UserProfileCommandService(
        unified_memory=unified_memory,
        query_service=query_service,
        portrait_repository=portrait_repository,
        portrait_builder=portrait_builder,
    )
    return query_service, command_service


@profile_router.get("/me", response_model=UserProfileProjection)
async def get_my_profile() -> UserProfileProjection:
    """Return the current local user's profile projection."""
    query_service, _ = _build_services()
    return await query_service.get_current_profile(DEFAULT_USER_ID)


@profile_router.patch("/me", response_model=UserProfileProjection)
async def update_my_profile(patch: ProfileUpdatePatch) -> UserProfileProjection:
    """Persist profile settings through L2 assertions and refresh projection."""
    _, command_service = _build_services()
    try:
        return await command_service.update_from_settings(patch, user_id=DEFAULT_USER_ID)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@profile_router.post("/me/refresh", response_model=UserProfileProjection)
async def refresh_my_profile() -> UserProfileProjection:
    """Rebuild the current local user's profile projection from L2."""
    _, command_service = _build_services()
    return await command_service.refresh_from_memory(DEFAULT_USER_ID)


__all__ = ["profile_router"]
