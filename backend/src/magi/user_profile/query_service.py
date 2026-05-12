"""Read facade for current user profile projections."""

from __future__ import annotations

from .models import DEFAULT_USER_ID, UserProfileProjection
from .projection_builder import UserProfileProjectionBuilder
from .projection_repository import UserProfileProjectionRepository


class UserProfileQueryService:
    """Serve profile projections, rebuilding from L2 when missing."""

    def __init__(
        self,
        *,
        repository: UserProfileProjectionRepository,
        builder: UserProfileProjectionBuilder,
    ):
        self._repository = repository
        self._builder = builder

    async def get_current_profile(self, user_id: str = DEFAULT_USER_ID) -> UserProfileProjection:
        projection = await self._repository.get(user_id)
        if projection is not None:
            return projection
        projection = await self._builder.build(user_id)
        return await self._repository.upsert(projection)

    async def refresh_profile(self, user_id: str = DEFAULT_USER_ID) -> UserProfileProjection:
        projection = await self._builder.build(user_id)
        return await self._repository.upsert(projection)