"""Shared module lifecycle orchestrator for backend startup/shutdown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

from ..core.logger import get_logger

logger = get_logger(__name__)

AsyncHook = Callable[[], Awaitable[None]]


async def _noop() -> None:
    """Default no-op hook."""


@dataclass(frozen=True)
class LifecycleModule:
    """Single module lifecycle hooks."""

    name: str
    init: AsyncHook = _noop
    post_init: AsyncHook = _noop
    shutdown: AsyncHook = _noop


class ModuleLifecycleOrchestrator:
    """Run module init/post-init/shutdown phases in deterministic order."""

    def __init__(self, modules: Iterable[LifecycleModule]):
        self._modules = list(modules)
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
