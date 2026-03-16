"""L1 Application Infrastructure lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext
from ..core.logger import get_logger
from ..utils.runtime import get_runtime_paths, init_runtime_data
from ..core.database_initializer import DatabaseInitializer, set_database_initializer

logger = get_logger(__name__)


class CoreDependenciesModule(LifecycleModule):
    """Initialize low-level runtime paths and host resources (L1)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(name="runtime_core_dependencies")
        self._context = context

    async def init(self) -> None:
        init_runtime_data()
        self._context.core.runtime_paths = get_runtime_paths()
        logger.info("Runtime directory: %s", self._context.core.runtime_paths.base_dir)

        db_initializer = DatabaseInitializer(data_dir=self._context.core.runtime_paths.data_dir)
        await db_initializer.initialize_all()
        set_database_initializer(db_initializer)
        self._context.core.db_initializer = db_initializer
        logger.info("Database initialization completed")
