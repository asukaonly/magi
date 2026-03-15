"""Shared module lifecycle orchestrator for backend startup/shutdown."""

from __future__ import annotations

from collections import deque
from typing import Awaitable, Callable, Iterable, Sequence

from ..core.logger import get_logger

logger = get_logger(__name__)

AsyncHook = Callable[[], Awaitable[None]]


async def _noop() -> None:
    """Default no-op hook."""


class LifecycleModule:
    """Base lifecycle module with optional hook-based constructor."""

    def __init__(
        self,
        name: str,
        *,
        dependencies: Sequence[str] | None = None,
        init: AsyncHook | None = None,
        post_init: AsyncHook | None = None,
        shutdown: AsyncHook | None = None,
    ) -> None:
        self.name = name
        self.dependencies = tuple(dependencies or ())
        self._init_hook = init
        self._post_init_hook = post_init
        self._shutdown_hook = shutdown

    async def init(self) -> None:
        """Initialize module resources."""
        if self._init_hook is None:
            await _noop()
            return
        await self._init_hook()

    async def post_init(self) -> None:
        """Initialize cross-module links after all modules are initialized."""
        if self._post_init_hook is None:
            await _noop()
            return
        await self._post_init_hook()

    async def shutdown(self) -> None:
        """Release module resources."""
        if self._shutdown_hook is None:
            await _noop()
            return
        await self._shutdown_hook()


class ModuleLifecycleOrchestrator:
    """Run module init/post-init/shutdown phases in dependency-safe order."""

    def __init__(self, modules: Iterable[LifecycleModule]):
        self._modules = self._resolve_order(list(modules))
        self._initialized_modules: list[LifecycleModule] = []
        self._started = False

    async def startup(self) -> None:
        """Run init for all modules, then run post-init for all initialized modules."""
        if self._started:
            logger.warning("Lifecycle startup skipped: already started")
            return

        initialized: list[LifecycleModule] = []
        try:
            for module in self._modules:
                logger.info("Lifecycle module init", module=module.name)
                await module.init()
                initialized.append(module)

            for module in initialized:
                logger.info("Lifecycle module post-init", module=module.name)
                await module.post_init()

            self._initialized_modules = initialized
            self._started = True
            logger.info("Lifecycle startup completed", module_count=len(initialized))
        except Exception:
            await self._shutdown_modules(initialized)
            raise

    async def shutdown(self) -> None:
        """Shutdown initialized modules in reverse order."""
        if not self._initialized_modules:
            self._started = False
            return

        initialized = list(self._initialized_modules)
        await self._shutdown_modules(initialized)
        self._initialized_modules = []
        self._started = False
        logger.info("Lifecycle shutdown completed", module_count=len(initialized))

    async def _shutdown_modules(self, modules: list[LifecycleModule]) -> None:
        for module in reversed(modules):
            try:
                logger.info("Lifecycle module shutdown", module=module.name)
                await module.shutdown()
            except Exception as exc:
                logger.warning("Lifecycle module shutdown failed", module=module.name, error=str(exc))

    def _resolve_order(self, modules: list[LifecycleModule]) -> list[LifecycleModule]:
        module_by_name: dict[str, LifecycleModule] = {}
        for module in modules:
            if module.name in module_by_name:
                raise ValueError(f"Duplicate lifecycle module name: {module.name}")
            module_by_name[module.name] = module

        for module in modules:
            for dependency in module.dependencies:
                if dependency not in module_by_name:
                    raise ValueError(
                        f"Lifecycle module '{module.name}' depends on unknown module '{dependency}'"
                    )

        order_index = {module.name: index for index, module in enumerate(modules)}
        indegree = {module.name: len(module.dependencies) for module in modules}
        reverse_edges: dict[str, list[str]] = {module.name: [] for module in modules}
        for module in modules:
            for dependency in module.dependencies:
                reverse_edges[dependency].append(module.name)

        queue = deque(
            sorted(
                [module.name for module in modules if indegree[module.name] == 0],
                key=lambda name: order_index[name],
            )
        )

        ordered_names: list[str] = []
        while queue:
            current = queue.popleft()
            ordered_names.append(current)
            for dependent in sorted(reverse_edges[current], key=lambda name: order_index[name]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)

        if len(ordered_names) != len(modules):
            unresolved = sorted(name for name, value in indegree.items() if value > 0)
            raise ValueError(
                f"Lifecycle dependency cycle detected among modules: {', '.join(unresolved)}"
            )

        return [module_by_name[name] for name in ordered_names]
