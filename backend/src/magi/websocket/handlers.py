"""
WebSocket message handlers with registry pattern.
"""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from fastapi import WebSocket

from ..api.avatar_paths import resolve_avatar_public_url
from ..core.logger import get_logger

if TYPE_CHECKING:
    from .connection_manager import ConnectionManager

logger = get_logger(__name__)


@dataclass
class WebSocketContext:
    """Context for WebSocket message handling."""

    sid: str
    websocket: WebSocket
    manager: "ConnectionManager"


class MessageHandlerRegistry:
    """Registry for WebSocket message handlers with decorator-based registration."""

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[[WebSocketContext, Dict[str, Any]], Any]] = {}

    def register(self, message_type: str) -> Callable:
        """Register a handler for a message type."""

        def decorator(func: Callable[[WebSocketContext, Dict[str, Any]], Any]) -> Callable:
            self._handlers[message_type] = func
            return func

        return decorator

    async def dispatch(self, ctx: WebSocketContext, data: dict) -> Optional[dict]:
        """Dispatch a message to the appropriate handler."""
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
        except Exception as exc:
            logger.error("Handler error", sid=ctx.sid, type=message_type, error=str(exc), exc_info=True)
            return {"type": "error", "message": f"Handler error: {str(exc)}"}


handler_registry = MessageHandlerRegistry()


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
    """Handle ping requests."""
    logger.debug("Ping received", sid=ctx.sid)
    return {"type": "pong"}


@handler_registry.register("get_personality")
async def handle_get_personality(ctx: WebSocketContext, data: dict) -> dict:
    """Handle personality info requests."""
    try:
        from ..api.services.personality_state_service import get_current_personality_name
        from ..personality.loader import PersonalityLoader
        from ..utils.runtime import get_runtime_paths

        current_name = get_current_personality_name()
        runtime_paths = get_runtime_paths()
        loader = PersonalityLoader(str(runtime_paths.personalities_dir))
        config = loader.load(current_name)
        greetings = config.cached_phrases.on_wake or config.cached_phrases.on_init
        greeting = random.choice(greetings) if greetings else f"Hello, I am {config.name}."
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
    except Exception as exc:
        logger.error("Failed to get personality info", sid=ctx.sid, error=str(exc))
        return {"type": "error", "message": f"Failed to get personality info: {str(exc)}"}


@handler_registry.register("send_message")
async def handle_send_message(ctx: WebSocketContext, data: dict) -> dict:
    """Handle user messages sent via WebSocket."""
    try:
        from ..api.services import dispatch_user_message

        user_id = data.get("user_id", "web_user")
        session_id = data.get("session_id")
        message = data.get("message", "")

        if not message:
            return {"type": "error", "message": "Message is required"}
        if not str(session_id or "").strip():
            return {"type": "error", "message": "Session ID is required"}

        outcome = await dispatch_user_message(
            source="websocket",
            user_id=user_id,
            message=message,
            session_id=session_id,
            client_turn_id=str(data.get("client_turn_id") or "").strip() or None,
            runtime_namespace=str(
                data.get("runtime_namespace")
                or (data.get("metadata") or {}).get("runtime_namespace")
                or "web"
            ),
        )
        if not outcome.success:
            return {
                "type": "error",
                "message": outcome.error_message or "Failed to queue message.",
            }
        logger.info("Message queued via WS", sid=ctx.sid, user=user_id, session=outcome.session_id)

        return {
            "type": "message_sent",
            "data": {
                "user_id": user_id,
                "session_id": outcome.session_id,
                "turn_id": outcome.turn_id,
                "timestamp": time.time(),
            },
        }
    except Exception as exc:
        logger.error("Failed to send message via WS", sid=ctx.sid, error=str(exc))
        return {"type": "error", "message": f"Failed to send message: {str(exc)}"}


@handler_registry.register("get_history")
async def handle_get_history(ctx: WebSocketContext, data: dict) -> dict:
    """Handle conversation history requests."""
    try:
        from ..api.services import get_chat_read_service

        user_id = data.get("user_id", "web_user")
        session_id = data.get("session_id")
        resolved_session = str(session_id or "").strip()
        if not resolved_session:
            return {"type": "error", "message": "Session ID is required"}

        read_service = get_chat_read_service()
        history = read_service.get_display_history(user_id, resolved_session)

        messages = [msg.to_dict() for msg in history]

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
        return {
            "type": "history",
            "data": {
                "user_id": data.get("user_id", "web_user"),
                "session_id": data.get("session_id"),
                "messages": [],
                "count": 0,
            },
        }
    except Exception as exc:
        logger.error("Failed to get history", sid=ctx.sid, error=str(exc))
        return {"type": "error", "message": f"Failed to get history: {str(exc)}"}
