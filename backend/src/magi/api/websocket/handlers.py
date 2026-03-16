"""
WebSocket message handlers with registry pattern.

Provides a modular message handling system for WebSocket connections.
"""
from __future__ import annotations

import json
import random
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from fastapi import WebSocket

from ..avatar_paths import resolve_avatar_public_url
from ...core.logger import get_logger

if TYPE_CHECKING:
    from ..websocket import ConnectionManager

logger = get_logger(__name__)


@dataclass
class WebSocketContext:
    """Context for WebSocket message handling."""

    sid: str
    websocket: WebSocket
    manager: "ConnectionManager"


class MessageHandlerRegistry:
    """Registry for WebSocket message handlers with decorator-based registration."""

    def __init__(self):
        self._handlers: Dict[str, Callable[[WebSocketContext, Dict[str, Any]], Any]] = {}

    def register(self, message_type: str) -> Callable:
        """
        Decorator to register a handler for a message type.

        Usage:
            @handler_registry.register("subscribe")
            async def handle_subscribe(ctx: WebSocketContext, data: dict) -> dict | None:
                ...
        """

        def decorator(func: Callable[[WebSocketContext, Dict[str, Any]], Any]) -> Callable:
            self._handlers[message_type] = func
            return func

        return decorator

    async def dispatch(self, ctx: WebSocketContext, data: dict) -> Optional[dict]:
        """
        Dispatch a message to the appropriate handler.

        Args:
            ctx: WebSocket context with connection details
            data: Parsed JSON message data

        Returns:
            Response dict to send back, or None if no response needed
        """
        message_type = data.get("type")
        if not message_type:
            logger.warning("Message missing type field", sid=ctx.sid)
            return {"type": "error", "message": "Message type is required"}

        handler = self._handlers.get(message_type)
        if not handler:
            logger.warning("Unknown message type", sid=ctx.sid, type=message_type)
            return {"type": "error", "message": f"Unknown message type: {message_type}"}

        try:
            return await handler(ctx, data)
        except Exception as e:
            logger.error("Handler error", sid=ctx.sid, type=message_type, error=str(e), exc_info=True)
            return {"type": "error", "message": f"Handler error: {str(e)}"}


# Global handler registry
handler_registry = MessageHandlerRegistry()


# ============================================================================
# Built-in message handlers
# ============================================================================


@handler_registry.register("subscribe")
async def handle_subscribe(ctx: WebSocketContext, data: dict) -> dict:
    """Handle room subscription requests."""
    channel = data.get("channel")
    if not channel:
        return {"type": "error", "message": "Channel is required for subscription"}

    ctx.manager.join_room(ctx.sid, channel)
    logger.info("Client subscribed", sid=ctx.sid, channel=channel)
    return {"type": "subscribed", "channel": channel, "sid": ctx.sid}


@handler_registry.register("unsubscribe")
async def handle_unsubscribe(ctx: WebSocketContext, data: dict) -> dict:
    """Handle room unsubscription requests."""
    channel = data.get("channel")
    if not channel:
        return {"type": "error", "message": "Channel is required for unsubscription"}

    ctx.manager.leave_room(ctx.sid, channel)
    logger.info("Client unsubscribed", sid=ctx.sid, channel=channel)
    return {"type": "unsubscribed", "channel": channel}


@handler_registry.register("ping")
async def handle_ping(ctx: WebSocketContext, data: dict) -> dict:
    """Handle ping requests for connection keep-alive."""
    logger.debug("Ping received", sid=ctx.sid)
    return {"type": "pong"}


@handler_registry.register("get_personality")
async def handle_get_personality(ctx: WebSocketContext, data: dict) -> dict:
    """Handle personality info requests."""
    try:
        from ...runtime.services.personality_state import get_current_personality
        from ...personality.loader import PersonalityLoader
        from ...utils.runtime import get_runtime_paths

        current_name = get_current_personality()
        runtime_paths = get_runtime_paths()
        loader = PersonalityLoader(str(runtime_paths.personalities_dir))
        config = loader.load(current_name)
        greetings = config.cached_phrases.on_wake or config.cached_phrases.on_init
        greeting = random.choice(greetings) if greetings else f"Hello, I am {config.name}."

        # Handle avatar URL
        avatar = resolve_avatar_public_url(config.avatar or "")

        logger.info("Sent personality info", sid=ctx.sid, name=config.name)
        return {
            "type": "personality_info",
            "data": {
                "name": config.name,
                "avatar": avatar,
                "greeting": greeting,
            },
        }
    except Exception as e:
        logger.error("Failed to get personality info", sid=ctx.sid, error=str(e))
        return {"type": "error", "message": f"Failed to get personality info: {str(e)}"}


@handler_registry.register("send_message")
async def handle_send_message(ctx: WebSocketContext, data: dict) -> dict:
    """Handle user messages sent via WebSocket."""
    try:
        from ...agent import get_agent_runtime
        from ...events.events import Event, EventTypes
        from ..services import get_chat_read_service
        from ...events.service_access import get_message_bus

        user_id = data.get("user_id", "web_user")
        session_id = data.get("session_id")
        message = data.get("message", "")

        if not message:
            return {"type": "error", "message": "Message is required"}

        try:
            get_agent_runtime()
        except RuntimeError:
            return {
                "type": "error",
                "message": "AgentRuntime not initialized. Please complete onboarding or check the saved configuration.",
            }

        read_service = get_chat_read_service()
        resolved_session = session_id or read_service.get_current_session_id(user_id)

        message_data = {
            "message": message,
            "user_id": user_id,
            "session_id": resolved_session,
            "turn_id": str(data.get("client_turn_id") or "").strip() or f"turn_{uuid.uuid4().hex[:12]}",
            "timestamp": time.time(),
        }

        message_bus = get_message_bus()
        if message_bus:
            event = Event(
                type=EventTypes.USER_MESSAGE,
                data=message_data,
                source="websocket",
            )
            await message_bus.publish(event)
            logger.info(
                "Message queued via WS",
                sid=ctx.sid,
                user=user_id,
                session=resolved_session,
            )

        return {
            "type": "message_sent",
            "data": {
                "user_id": user_id,
                "session_id": resolved_session,
                "turn_id": message_data["turn_id"],
                "timestamp": time.time(),
            },
        }
    except Exception as e:
        logger.error("Failed to send message via WS", sid=ctx.sid, error=str(e))
        return {"type": "error", "message": f"Failed to send message: {str(e)}"}


@handler_registry.register("get_current_session")
async def handle_get_current_session(ctx: WebSocketContext, data: dict) -> dict:
    """Handle current session ID requests."""
    try:
        from ..services import get_chat_read_service

        user_id = data.get("user_id", "web_user")
        read_service = get_chat_read_service()
        session_id = read_service.get_current_session_id(user_id)

        return {
            "type": "current_session",
            "data": {
                "user_id": user_id,
                "session_id": session_id,
            },
        }
    except RuntimeError:
        # Agent not initialized
        return {
            "type": "current_session",
            "data": {
                "user_id": data.get("user_id", "web_user"),
                "session_id": None,
            },
        }
    except Exception as e:
        logger.error("Failed to get current session", sid=ctx.sid, error=str(e))
        return {"type": "error", "message": f"Failed to get current session: {str(e)}"}


@handler_registry.register("get_history")
async def handle_get_history(ctx: WebSocketContext, data: dict) -> dict:
    """Handle conversation history requests."""
    try:
        from ..services import get_chat_read_service

        user_id = data.get("user_id", "web_user")
        session_id = data.get("session_id")

        read_service = get_chat_read_service()
        resolved_session = session_id or read_service.get_current_session_id(user_id)
        history = read_service.get_display_history(user_id, resolved_session)

        messages = [
            {
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": int(msg.get("timestamp", time.time())),
                "turn_id": msg.get("turn_id"),
                "kind": msg.get("kind"),
                "trace_summary": msg.get("trace_summary"),
                "trace_available": bool(msg.get("trace_available")),
            }
            for msg in history
        ]

        return {
            "type": "history",
            "data": {
                "user_id": user_id,
                "session_id": resolved_session,
                "messages": messages,
                "count": len(messages),
            },
        }
    except RuntimeError:
        # Agent not initialized
        return {
            "type": "history",
            "data": {
                "user_id": data.get("user_id", "web_user"),
                "session_id": data.get("session_id"),
                "messages": [],
                "count": 0,
            },
        }
    except Exception as e:
        logger.error("Failed to get history", sid=ctx.sid, error=str(e))
        return {"type": "error", "message": f"Failed to get history: {str(e)}"}
