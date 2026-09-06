"""Hooks subsystem lifecycle module.

Initializes ``HookRegistry`` + ``HookGateway`` in the bootstrap context so
other layers can resolve them via ``RuntimeBootstrapContext.hooks.gateway``.
Loads handlers from ``~/.claude/settings.json`` (Phase 3) when present.
"""

from __future__ import annotations

from ..bootstrap.context import RuntimeBootstrapContext
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from .gateway import HookGateway
from .registry import HookRegistry
from .user_settings import load_user_hook_handlers

logger = get_logger(__name__)


class HooksModule(LifecycleModule):
    """Initialize ``HookGateway`` shared across the runtime."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_hooks",
            dependencies=("runtime_configuration", "runtime_command_queue"),
        )
        self._context = context

    async def init(self) -> None:
        from dependency_injector import providers

        from ..core.container import get_container

        registry = self._context.hooks.registry
        if registry is None:
            registry = HookRegistry()
        gateway = HookGateway(registry)
        self._context.hooks.registry = registry
        self._context.hooks.gateway = gateway

        container = get_container()
        container.hook_registry.override(providers.Object(registry))
        container.hook_gateway.override(providers.Object(gateway))

        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("User hook loading held for full-clear recovery")
            return
        await self._load_user_settings_handlers(registry)
        logger.info("Hooks runtime initialized handlers=%d", registry.total())

    async def shutdown(self) -> None:
        from ..core.container import get_container

        if self._context.hooks.registry is not None:
            self._context.hooks.registry.clear()
        self._context.hooks.registry = None
        self._context.hooks.gateway = None
        try:
            container = get_container()
            container.hook_registry.reset_override()
            container.hook_gateway.reset_override()
        except Exception:
            pass

    async def _load_user_settings_handlers(self, registry: HookRegistry) -> None:
        """Load handlers declared in ~/.claude/settings.json (Phase 3).

        Best-effort: a missing file is fine, a malformed file is logged but
        does not abort startup.
        """
        try:
            await load_user_hook_handlers(registry)
        except Exception:
            logger.exception("failed loading user hook handlers from settings.json")


__all__ = ["HooksModule"]
