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
        await shutdown_chat_agent()

    return app

