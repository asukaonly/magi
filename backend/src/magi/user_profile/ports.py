"""User projection persistence contracts and composed repositories."""

from dataclasses import dataclass
from typing import Protocol

from .models import UserPortraitProjection, UserProfileProjection


class ProfileRepository(Protocol):
    async def get(self, user_id: str) -> UserProfileProjection | None: ...
    async def upsert(self, projection: UserProfileProjection) -> UserProfileProjection: ...


class PortraitRepository(Protocol):
    async def get(self, user_id: str) -> UserPortraitProjection | None: ...
    async def upsert(self, projection: UserPortraitProjection) -> UserPortraitProjection: ...


@dataclass(frozen=True, slots=True)
class UserProjectionRepositories:
    profile: ProfileRepository
    portrait: PortraitRepository
