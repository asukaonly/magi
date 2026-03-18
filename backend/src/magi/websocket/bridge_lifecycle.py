"""Lifecycle module for websocket bridge subscriptions."""

from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI

from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from ..core.runtime_bindings import require_message_bus
from ..events.events import Event, EventTypes
from .connection_manager import manager

logger = get_logger(__name__, category="API")

WORKER_AGENT_EVENT_TYPES = (
    "WORKER_AGENT_PROGRESS",
    "WORKER_AGENT_COMPLETED",
    "WORKER_AGENT_FAILED",
)
TRACE_EVENT_TYPES = WORKER_AGENT_EVENT_TYPES + (
    "CHAT_TOOL_LOOP_STEP",
    "TOOL_INTERACTION",
    "TOOL_INVOKED",
    "TURN_TRACE_STARTED",
    "TURN_TRACE_COMPLETED",
    "TURN_TRACE_FAILED",
    "TRACE_NODE_STARTED",
    "TRACE_NODE_COMPLETED",
    "TRACE_NODE_FAILED",
)
DEFAULT_WEBSOCKET_BRIDGE_RETRY_INTERVAL_SECONDS = 0.5


class WebSocketBridgeLifecycleModule(LifecycleModule):
    """Bridge message bus events to connected WebSocket clients."""

    def __init__(self, app: FastAPI, retry_interval_seconds: float = DEFAULT_WEBSOCKET_BRIDGE_RETRY_INTERVAL_SECONDS):
        super().__init__(
            name="websocket_bridge",
            dependencies=("runtime_system",),
        )
        self._app = app
        self._retry_interval_seconds = retry_interval_seconds

    async def init(self) -> None:
        state = self._app.state
        state.ai_response_subscription_id = None
        state.worker_agent_subscription_ids = []
        state.websocket_bridge_message_bus = None
        state.websocket_bridge_retry_task = None

    async def post_init(self) -> None:
        subscribed = await self._ensure_subscriptions()
        if subscribed:
            return

        logger.info(
            "Message bus unavailable at startup; scheduling websocket bridge retry",
            pid=os.getpid(),
        )
        self._app.state.websocket_bridge_retry_task = asyncio.create_task(self._retry_subscriptions())

    async def shutdown(self) -> None:
        state = self._app.state

        retry_task = getattr(state, "websocket_bridge_retry_task", None)
        if retry_task:
            retry_task.cancel()
            try:
                await retry_task
            except asyncio.CancelledError:
                pass
            finally:
                state.websocket_bridge_retry_task = None

        try:
            message_bus = require_message_bus()
        except RuntimeError:
            message_bus = None
        bridge_bus = getattr(state, "websocket_bridge_message_bus", None) or message_bus
        sub_id = getattr(state, "ai_response_subscription_id", None)
        if bridge_bus and sub_id:
            try:
                await bridge_bus.unsubscribe(sub_id)
            except Exception as exc:
                logger.warning(f"Failed to unsubscribe AI_RESPONSE bridge: {exc}")

        worker_sub_ids = getattr(state, "worker_agent_subscription_ids", None) or []
        if bridge_bus and worker_sub_ids:
            for worker_sub_id in worker_sub_ids:
                try:
                    await bridge_bus.unsubscribe(worker_sub_id)
                except Exception as exc:
                    logger.warning(f"Failed to unsubscribe worker bridge {worker_sub_id}: {exc}")

        state.ai_response_subscription_id = None
        state.worker_agent_subscription_ids = []
        state.websocket_bridge_message_bus = None

    async def _ensure_subscriptions(self) -> bool:
        """Subscribe to message bus events for WebSocket broadcast."""
        state = self._app.state
        try:
            message_bus = require_message_bus()
        except RuntimeError:
            return False

        existing_sub_id = getattr(state, "ai_response_subscription_id", None)
        existing_bus = getattr(state, "websocket_bridge_message_bus", None)
        if existing_sub_id and existing_bus is message_bus:
            return True

        async def _on_ai_response(event: Event) -> None:
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
            await manager.broadcast("agent_response", data, room=room_name)

        async def _on_trace_event(event: Event) -> None:
            data = event.data if isinstance(event.data, dict) else {}
            tags = data.get("tags") if isinstance(data.get("tags"), dict) else {}
            user_id = str(data.get("user_id") or tags.get("user_id") or "").strip()
            session_id = str(data.get("session_id") or tags.get("session_id") or "").strip()
            turn_id = str(data.get("turn_id", "")).strip()

            if not user_id:
                return

            trace_payload = {
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "event_type": event.type,
            }
            if "orchestration_id" in data:
                trace_payload["orchestration_id"] = data["orchestration_id"]
            if "iteration" in data:
                trace_payload["iteration"] = data["iteration"]
            if "span_id" in data:
                trace_payload["span_id"] = data["span_id"]
            if "parent_span_id" in data:
                trace_payload["parent_span_id"] = data["parent_span_id"]
            if "node_type" in data:
                trace_payload["node_type"] = data["node_type"]
            if "status" in data:
                trace_payload["status"] = data["status"]

            await manager.broadcast(
                "execution_trace_update",
                trace_payload,
                room=f"user_{user_id}",
            )

        stale_sub_id = getattr(state, "ai_response_subscription_id", None)
        stale_trace_sub_ids = getattr(state, "worker_agent_subscription_ids", None) or []
        stale_bus = getattr(state, "websocket_bridge_message_bus", None)
        if stale_bus is not None and stale_bus is not message_bus:
            if stale_sub_id:
                try:
                    await stale_bus.unsubscribe(stale_sub_id)
                except Exception as exc:
                    logger.warning(f"Failed to unsubscribe stale AI_RESPONSE bridge: {exc}")
            for stale_trace_sub_id in stale_trace_sub_ids:
                try:
                    await stale_bus.unsubscribe(stale_trace_sub_id)
                except Exception as exc:
                    logger.warning(f"Failed to unsubscribe stale trace bridge {stale_trace_sub_id}: {exc}")

        sub_id = await message_bus.subscribe(
            EventTypes.AI_RESPONSE,
            _on_ai_response,
            propagation_mode="broadcast",
        )
        state.ai_response_subscription_id = sub_id
        state.websocket_bridge_message_bus = message_bus
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
        state.worker_agent_subscription_ids = trace_sub_ids
        logger.info(
            "Subscribed trace events for websocket bridge",
            count=len(trace_sub_ids),
            pid=os.getpid(),
        )
        return True

    async def _retry_subscriptions(self) -> None:
        attempts = 0
        while True:
            try:
                if await self._ensure_subscriptions():
                    logger.info(
                        "Deferred websocket bridge subscription established",
                        attempts=attempts,
                        pid=os.getpid(),
                    )
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Deferred websocket bridge subscription attempt failed",
                    attempts=attempts + 1,
                    error=str(exc),
                    pid=os.getpid(),
                )

            attempts += 1
            if attempts % 20 == 0:
                logger.info(
                    "Waiting for message bus before websocket bridge subscription",
                    attempts=attempts,
                    pid=os.getpid(),
                )
            await asyncio.sleep(self._retry_interval_seconds)
