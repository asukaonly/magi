"""Backend application entrypoint with unified lifecycle orchestration."""

from __future__ import annotations

import os

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
TRACE_EVENT_TYPES = WORKER_AGENT_EVENT_TYPES + (
    "CHAT_TOOL_LOOP_STEP",
    "TOOL_INTERACTION",
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
        from .api.services import get_chat_trace_read_service

        message_bus = get_message_bus()
        if message_bus:
            trace_service = get_chat_trace_read_service()

            async def _broadcast_trace_update(data: dict) -> None:
                user_id = str(data.get("user_id", "")).strip()
                session_id = str(data.get("session_id", "")).strip()
                turn_id = str(data.get("turn_id", "")).strip()
                if not user_id or not session_id or not turn_id:
                    return
                snapshot = trace_service.get_trace_snapshot(
                    user_id=user_id,
                    session_id=session_id,
                    turn_id=turn_id,
                )
                if not isinstance(snapshot, dict):
                    return
                await manager.broadcast(
                    "execution_trace_update",
                    {
                        "user_id": user_id,
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "trace_summary": snapshot.get("summary"),
                        "trace_available": bool(snapshot.get("summary", {}).get("trace_available")),
                        "orchestration_id": snapshot.get("orchestration_id"),
                    },
                    room=f"user_{user_id}",
                )

            async def _on_ai_response(event: Event):
                data = event.data if isinstance(event.data, dict) else {}
                user_id = str(data.get("user_id", "")).strip()
                session_id = str(data.get("session_id", "")).strip()
                turn_id = str(data.get("turn_id", "")).strip()
                if not user_id:
                    logger.warning(
                        "AI_RESPONSE missing user_id; skip websocket broadcast",
                        turn_id=turn_id or None,
                        session_id=session_id or None,
                        pid=os.getpid(),
                    )
                    return
                enriched = dict(data)
                if session_id and turn_id:
                    snapshot = trace_service.get_trace_snapshot(
                        user_id=user_id,
                        session_id=session_id,
                        turn_id=turn_id,
                    )
                    if isinstance(snapshot, dict):
                        enriched["trace_summary"] = snapshot.get("summary")
                        enriched["trace_available"] = bool(snapshot.get("summary", {}).get("trace_available"))
                        enriched["orchestration_id"] = snapshot.get("orchestration_id")
                room_name = f"user_{user_id}"
                room_clients = manager.get_clients_in_room(room_name)
                logger.info(
                    "AI_RESPONSE received by websocket bridge",
                    user_id=user_id,
                    session_id=session_id or None,
                    turn_id=turn_id or None,
                    room=room_name,
                    room_clients=room_clients,
                    pid=os.getpid(),
                )
                await manager.broadcast("agent_response", enriched, room=room_name)

            async def _on_trace_event(event: Event):
                data = event.data if isinstance(event.data, dict) else {}
                await _broadcast_trace_update(data)

            sub_id = await message_bus.subscribe(
                EventTypes.AI_RESPONSE,
                _on_ai_response,
                propagation_mode="broadcast",
            )
            app.state.ai_response_subscription_id = sub_id
            logger.info(
                "Subscribed AI_RESPONSE for websocket bridge",
                subscription_id=sub_id,
                pid=os.getpid(),
            )
            trace_sub_ids = []
            for trace_event_type in TRACE_EVENT_TYPES:
                worker_sub_id = await message_bus.subscribe(
                    trace_event_type,
                    _on_trace_event,
                    propagation_mode="broadcast",
                )
                trace_sub_ids.append(worker_sub_id)
            app.state.worker_agent_subscription_ids = trace_sub_ids
            logger.info(
                "Subscribed trace events for websocket bridge",
                count=len(trace_sub_ids),
                pid=os.getpid(),
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
        worker_sub_ids = getattr(app.state, "worker_agent_subscription_ids", None) or []
        if message_bus and worker_sub_ids:
            for worker_sub_id in worker_sub_ids:
                try:
                    await message_bus.unsubscribe(worker_sub_id)
                except Exception as exc:
                    logger.warning(f"Failed to unsubscribe worker bridge {worker_sub_id}: {exc}")
        await shutdown_chat_agent()

    return app
