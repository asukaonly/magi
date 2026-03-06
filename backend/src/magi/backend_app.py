"""Backend application entrypoint with unified lifecycle orchestration."""

from __future__ import annotations

from fastapi import FastAPI

from .api.app import create_app as create_api_app
from .api.connection_manager import manager
from .core.container import wire_container
from .core.logger import get_logger
from .events.events import Event, EventTypes
from .runtime import (
    RuntimeBindings,
    configure_runtime_bindings,
    initialize_chat_agent,
    shutdown_chat_agent,
)

logger = get_logger(__name__, category="API")
WORKER_AGENT_EVENT_TYPES = (
    "WORKER_AGENT_PROGRESS",
    "WORKER_AGENT_COMPLETED",
    "WORKER_AGENT_FAILED",
)


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


def create_backend_app() -> FastAPI:
    """
    Create full backend app with unified module initialization.

    This is the outermost entrypoint for backend startup.
    """
    # Wire DI container to modules
    wire_container()
    logger.info("DI container wired")

    app = create_api_app()
    configure_runtime_bindings(_build_runtime_bindings())

    @app.on_event("startup")
    async def startup_event():
        """Initialize runtime modules and bridges."""
        await initialize_chat_agent()

        from .api.routers.messages import get_message_bus

        message_bus = get_message_bus()
        if message_bus:
            async def _on_ai_response(event: Event):
                data = event.data if isinstance(event.data, dict) else {}
                user_id = str(data.get("user_id", "")).strip()
                if not user_id:
                    return
                await manager.broadcast("agent_response", data, room=f"user_{user_id}")

            async def _on_worker_agent_update(event: Event):
                data = event.data if isinstance(event.data, dict) else {}
                user_id = str(data.get("user_id", "")).strip()
                if not user_id:
                    return
                enriched_data = {
                    key: value
                    for key, value in dict(data).items()
                    if key != "worker_result"
                }
                enriched_data["event_type"] = event.type
                await manager.broadcast("worker_agent_update", enriched_data, room=f"user_{user_id}")

            sub_id = await message_bus.subscribe(
                EventTypes.AI_RESPONSE,
                _on_ai_response,
                propagation_mode="broadcast",
            )
            app.state.ai_response_subscription_id = sub_id
            logger.info(
                "Subscribed AI_RESPONSE for websocket bridge | subscription_id=%s",
                sub_id,
            )
            worker_sub_ids = []
            for worker_event_type in WORKER_AGENT_EVENT_TYPES:
                worker_sub_id = await message_bus.subscribe(
                    worker_event_type,
                    _on_worker_agent_update,
                    propagation_mode="broadcast",
                )
                worker_sub_ids.append(worker_sub_id)
            app.state.worker_agent_subscription_ids = worker_sub_ids
            logger.info("Subscribed worker agent events for websocket bridge | count=%s", len(worker_sub_ids))

    @app.on_event("shutdown")
    async def shutdown_event():
        """Stop runtime modules and detach bridges."""
        from .api.routers.messages import get_message_bus

        message_bus = get_message_bus()
        sub_id = getattr(app.state, "ai_response_subscription_id", None)
        if message_bus and sub_id:
            try:
                await message_bus.unsubscribe(sub_id)
            except Exception as exc:
                logger.warning(f"Failed to unsubscribe AI_RESPONSE bridge: {exc}")
        worker_sub_ids = getattr(app.state, "worker_agent_subscription_ids", None) or []
        if message_bus and worker_sub_ids:
            for worker_sub_id in worker_sub_ids:
                try:
                    await message_bus.unsubscribe(worker_sub_id)
                except Exception as exc:
                    logger.warning(f"Failed to unsubscribe worker bridge {worker_sub_id}: {exc}")
        await shutdown_chat_agent()

    return app
