"""Database migration lifecycle module (L1 infrastructure).

Owns the Alembic ``upgrade head`` step that brings every registered runtime
database to its latest committed schema revision. This lifecycle previously
lived inside ``CoreDependenciesModule`` (``core/lifecycle.py``); it was moved
here so the migration concern lives with the package that owns it, and so the
``core -> db`` import edge is removed. ``db`` now depends only on ``core.logger``
(a leaf), which keeps the unified logging pipeline while breaking the
``core <-> db`` package cycle.

Runs immediately after ``CoreDependenciesModule`` — it needs the runtime paths
and directories that module initializes — and before any module that opens one
of the migrated databases.
"""

from __future__ import annotations

from ..bootstrap.context import RuntimeBootstrapContext
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from .runner import run_upgrade_head

logger = get_logger(__name__)


class DatabaseMigrationModule(LifecycleModule):
    """Apply Alembic schema migrations for the core runtime databases (L1)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_database_migrations",
            dependencies=("runtime_core_dependencies",),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = self._context.core.runtime_paths
        if runtime_paths is None:
            raise RuntimeError("runtime paths is not initialized")
        run_upgrade_head(runtime_paths)
        logger.info("Database migrations completed")


__all__ = ["DatabaseMigrationModule"]
