"""Backend application entrypoint with unified lifecycle orchestration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import os

from fastapi import FastAPI

from .websocket.bridge_lifecycle import WebSocketBridgeLifecycleModule
from .websocket.http_app import create_transport_app
from .core.container import wire_container
from .core.logger import get_logger
from .bootstrap import (
    initialize_agent_runtime,
    shutdown_agent_runtime,
)
from .bootstrap.lifecycle import LifecycleModule, ModuleLifecycleOrchestrator
from .process_roles import ProcessRole, resolve_process_role

logger = get_logger(__name__, category="API")


class AppCoreDependenciesModule(LifecycleModule):
    """Initialize backend core dependencies."""

    def __init__(self) -> None:
        super().__init__(name="app_core_dependencies")

    async def init(self) -> None:
        wire_container()
        logger.info("DI container wired")


class RuntimeSystemModule(LifecycleModule):
    """Compose runtime subsystem lifecycle behind one app-level module."""

    def __init__(self, role: ProcessRole) -> None:
        super().__init__(
            name="runtime_system",
            dependencies=("app_core_dependencies",),
        )
        self._role = role

    async def init(self) -> None:
        await initialize_agent_runtime(role=self._role)

    async def shutdown(self) -> None:
        await shutdown_agent_runtime()


def _build_app_lifecycle_orchestrator(app: FastAPI, *, role: ProcessRole) -> ModuleLifecycleOrchestrator:
    websocket_bridge = WebSocketBridgeLifecycleModule(app)

    return ModuleLifecycleOrchestrator(
        modules=[
            AppCoreDependenciesModule(),
            RuntimeSystemModule(role),
            websocket_bridge,
        ]
    )


def create_backend_app(*, role: ProcessRole | None = None) -> FastAPI:
    """Create full backend app with lifecycle-managed module startup/shutdown."""
    resolved_role = role or resolve_process_role(env=os.environ)
    if resolved_role is ProcessRole.RUNTIME_WORKER:
        raise ValueError("Runtime worker role cannot create the FastAPI transport app")

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.backend_ready = False
        app.state.process_role = resolved_role.value
        orchestrator = _build_app_lifecycle_orchestrator(app, role=resolved_role)
        app.state.module_lifecycle_orchestrator = orchestrator
        await orchestrator.startup()
        app.state.backend_ready = True
        try:
            yield
        finally:
            app.state.backend_ready = False
            await orchestrator.shutdown()

    app = create_transport_app(lifespan=_lifespan)
    app.state.process_role = resolved_role.value

    return app
