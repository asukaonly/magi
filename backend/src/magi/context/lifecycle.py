"""L10 Context Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext


class ContextModule(LifecycleModule):
    """Reserve the L10 context lifecycle boundary."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_context",
            dependencies=("runtime_personality", "runtime_core_dependencies"),
        )
        self._context = context

    async def init(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None
