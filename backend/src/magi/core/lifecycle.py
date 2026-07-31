"""L1 Application Infrastructure lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext
from ..core.logger import get_logger
from ..utils.runtime import get_runtime_paths, init_runtime_data
from ..core.initialization_state import InitializationStateStore

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

        logger.info("Runtime directories initialized")


class InitializationStateModule(LifecycleModule):
    """Initialize the durable ledger for versioned startup work."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_initialization_state",
            dependencies=("runtime_core_dependencies",),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = self._context.core.runtime_paths
        if runtime_paths is None:
            raise RuntimeError("runtime paths is not initialized")
        store = InitializationStateStore(runtime_paths.initialization_state_db_path)
        await store.initialize()
        self._context.core.initialization_state = store
        logger.info("Initialization state store ready")

    async def shutdown(self) -> None:
        self._context.core.initialization_state = None
