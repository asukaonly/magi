"""Backend application entrypoint with unified lifecycle orchestration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from .api.app import create_app as create_api_app
from .api.websocket_bridge_lifecycle import WebSocketBridgeLifecycleModule
from .core.container import wire_container
from .core.logger import get_logger
from .runtime import (
    RuntimeBindings,
    configure_runtime_bindings,
    initialize_chat_agent,
    shutdown_chat_agent,
)
from .runtime.lifecycle import LifecycleModule, ModuleLifecycleOrchestrator

logger = get_logger(__name__, category="API")
WEBSOCKET_BRIDGE_RETRY_INTERVAL_SECONDS = 0.5


def _build_runtime_bindings() -> RuntimeBindings:
    """Build runtime-to-API bridge callbacks."""
    from .api.routers.messages import set_message_bus
    from .api.routers.personality_config import get_current_personality
    from .api.routers.skills import init_skills_module

    return RuntimeBindings(
        get_current_personality=get_current_personality,
        set_message_bus=set_message_bus,
        init_skills_module=init_skills_module,
    )


def _build_lifecycle_orchestrator(app: FastAPI) -> ModuleLifecycleOrchestrator:
    websocket_bridge = WebSocketBridgeLifecycleModule(
        app,
        retry_interval_seconds=WEBSOCKET_BRIDGE_RETRY_INTERVAL_SECONDS,
    )

    async def _init_container() -> None:
        wire_container()
        logger.info("DI container wired")

    async def _init_runtime_bindings() -> None:
        configure_runtime_bindings(_build_runtime_bindings())

    return ModuleLifecycleOrchestrator(
        modules=[
            LifecycleModule(name="container", init=_init_container),
            LifecycleModule(name="runtime_bindings", init=_init_runtime_bindings),
            LifecycleModule(name="agent_runtime", init=initialize_chat_agent, shutdown=shutdown_chat_agent),
            LifecycleModule(
                name="websocket_bridge",
                init=websocket_bridge.init,
                post_init=websocket_bridge.post_init,
                shutdown=websocket_bridge.shutdown,
            ),
        ]
    )


def create_backend_app() -> FastAPI:
    """Create full backend app with lifecycle-managed module startup/shutdown."""
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        orchestrator = _build_lifecycle_orchestrator(app)
        app.state.module_lifecycle_orchestrator = orchestrator
        await orchestrator.startup()
        try:
            yield
        finally:
            await orchestrator.shutdown()

    app = create_api_app(lifespan=_lifespan)

    return app
