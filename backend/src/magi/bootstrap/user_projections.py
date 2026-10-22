"""Compose projection repositories and connect memory-owned derivation jobs."""

from ..memory.unified_store import UnifiedMemoryStore
from ..user_profile.ports import UserProjectionRepositories
from ..user_profile.portrait_projection_repository import UserPortraitProjectionRepository
from ..user_profile.portrait_projection_scheduler import register_l2_portrait_projection_refresh
from ..user_profile.projection_repository import UserProfileProjectionRepository
from .context import RuntimeBootstrapContext


def configure_user_projection_runtime(
    context: RuntimeBootstrapContext,
    memory: UnifiedMemoryStore,
) -> None:
    repositories = UserProjectionRepositories(
        profile=UserProfileProjectionRepository(memory.memory_db_path),
        portrait=UserPortraitProjectionRepository(memory.memory_db_path),
    )
    context.memory.user_projection_repositories = repositories
    register_l2_portrait_projection_refresh(memory, repositories=repositories)
