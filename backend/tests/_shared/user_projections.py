"""Explicit projection repository composition for SQLite integration tests."""
from magi.user_profile.ports import UserProjectionRepositories
from magi.user_profile.projection_repository import UserProfileProjectionRepository
from magi.user_profile.portrait_projection_repository import UserPortraitProjectionRepository


def build_user_projection_repositories(db_path: str) -> UserProjectionRepositories:
    return UserProjectionRepositories(
        profile=UserProfileProjectionRepository(db_path),
        portrait=UserPortraitProjectionRepository(db_path),
    )
