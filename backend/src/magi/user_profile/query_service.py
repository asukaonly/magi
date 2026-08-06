"""Read facade for current user profile projections."""

from __future__ import annotations

from ..core.logger import get_logger
from .models import DEFAULT_USER_ID, UserProfileProjection
from .projection_builder import UserProfileProjectionBuilder
from .projection_freshness import profile_projection_is_stale
from .projection_repository import UserProfileProjectionRepository

logger = get_logger(__name__)


class UserProfileQueryService:
    """Serve profile projections rebuilt from current L2 profile assertions."""

    def __init__(
        self,
        *,
        repository: UserProfileProjectionRepository,
        builder: UserProfileProjectionBuilder,
    ):
        self._repository = repository
        self._builder = builder

    async def get_current_profile(self, user_id: str = DEFAULT_USER_ID) -> UserProfileProjection:
        return await self._read_or_rebuild(user_id=user_id, force=False)

    async def refresh_profile(self, user_id: str = DEFAULT_USER_ID) -> UserProfileProjection:
        return await self._read_or_rebuild(user_id=user_id, force=True)

    async def _read_or_rebuild(
        self,
        *,
        user_id: str,
        force: bool,
    ) -> UserProfileProjection:
        cached = await self._repository.get(user_id)
        if cached is not None and not force:
            try:
                is_stale = await profile_projection_is_stale(
                    cached,
                    user_id=user_id,
                    l2_store=self._builder.l2_store,
                )
            except Exception as exc:
                _log_projection_failure(
                    user_id=user_id,
                    stage="freshness",
                    error=exc,
                    used_last_good=True,
                )
                return cached
            if not is_stale:
                return cached

        try:
            projection = await self._builder.build(user_id)
            return await self._repository.upsert(projection)
        except Exception as exc:
            if cached is None:
                _log_projection_failure(
                    user_id=user_id,
                    stage="rebuild",
                    error=exc,
                    used_last_good=False,
                )
                raise
            _log_projection_failure(
                user_id=user_id,
                stage="rebuild",
                error=exc,
                used_last_good=True,
            )
            return cached


def _log_projection_failure(
    *,
    user_id: str,
    stage: str,
    error: Exception,
    used_last_good: bool,
) -> None:
    logger.error(
        "User profile projection input failed",
        user_id=user_id,
        projection_kind="profile",
        stage=stage,
        cached_kept=used_last_good,
        error_type=type(error).__name__,
    )
