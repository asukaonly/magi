"""Backend application entrypoint with unified lifecycle orchestration."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

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
    if not resolved_role.runs_transport:
        raise ValueError(f"Role '{resolved_role.value}' cannot create the FastAPI transport app")

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.backend_ready = False
        app.state.process_role = resolved_role.value
        orchestrator = _build_app_lifecycle_orchestrator(app, role=resolved_role)
        app.state.module_lifecycle_orchestrator = orchestrator
        await orchestrator.startup()
        app.state.backend_ready = True

        heartbeat_task = None
        heartbeat_stop = None
        heartbeat_status: dict[str, str] | None = None
        instance_id: str | None = None
        started_at_ms: int | None = None

        if resolved_role.runs_runtime:
            from .backend_runtime_worker import (
                _heartbeat_loop,
                _publish_runtime_heartbeat,
                _begin_runtime_drain,
                DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS,
            )

            instance_id = uuid.uuid4().hex
            started_at_ms = int(time.time() * 1000)
            heartbeat_status = {"value": "ready"}
            heartbeat_stop = asyncio.Event()

            await _publish_runtime_heartbeat(
                instance_id=instance_id,
                started_at_ms=started_at_ms,
                status="ready",
            )
            heartbeat_task = asyncio.create_task(
                _heartbeat_loop(
                    stop_event=heartbeat_stop,
                    instance_id=instance_id,
                    started_at_ms=started_at_ms,
                    status_ref=heartbeat_status,
                )
            )

        try:
            yield
        finally:
            app.state.backend_ready = False

            if resolved_role.runs_runtime and heartbeat_task is not None:
                from .backend_runtime_worker import (
                    _publish_runtime_heartbeat,
                    _begin_runtime_drain,
                    DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS,
                )

                if heartbeat_status is not None:
                    heartbeat_status["value"] = "draining"
                await _begin_runtime_drain(
                    timeout_seconds=DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS,
                )
                await _publish_runtime_heartbeat(
                    instance_id=instance_id,
                    started_at_ms=started_at_ms,
                    status="stopping",
                )
                heartbeat_stop.set()
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            await orchestrator.shutdown()

    app = create_transport_app(lifespan=_lifespan)
    app.state.process_role = resolved_role.value

    return app
