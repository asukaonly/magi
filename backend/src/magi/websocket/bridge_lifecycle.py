"""Lifecycle module for websocket bridge polling runtime notifications."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI

from ..api.services import get_chat_trace_read_service
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from ..core.runtime_bindings import require_runtime_trace_store
from ..runtime_trace import RuntimeNotificationRecord
from .connection_manager import manager

logger = get_logger(__name__, category="API")

DEFAULT_WEBSOCKET_BRIDGE_RETRY_INTERVAL_SECONDS = 0.5


class WebSocketBridgeLifecycleModule(LifecycleModule):
    """Poll runtime notifications and forward them to websocket clients."""

    def __init__(self, app: FastAPI, retry_interval_seconds: float = DEFAULT_WEBSOCKET_BRIDGE_RETRY_INTERVAL_SECONDS):
        super().__init__(
            name="websocket_bridge",
            dependencies=("runtime_system",),
        )
        self._app = app
        self._retry_interval_seconds = retry_interval_seconds

    async def init(self) -> None:
        state = self._app.state
        state.websocket_bridge_poll_task = None
        state.websocket_bridge_last_notification_id = 0

    async def post_init(self) -> None:
        store = require_runtime_trace_store()
        self._app.state.websocket_bridge_last_notification_id = await store.get_latest_notification_id()
        self._app.state.websocket_bridge_poll_task = asyncio.create_task(self._poll_notifications())

    async def shutdown(self) -> None:
        poll_task = getattr(self._app.state, "websocket_bridge_poll_task", None)
        if poll_task is None:
            return
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
        finally:
            self._app.state.websocket_bridge_poll_task = None

    async def _poll_notifications(self) -> None:
        while True:
            try:
                store = require_runtime_trace_store()
                last_id = int(getattr(self._app.state, "websocket_bridge_last_notification_id", 0) or 0)
                notifications = await store.list_notifications(after_id=last_id, limit=50)
                if not notifications:
                    await asyncio.sleep(self._retry_interval_seconds)
                    continue

                for notification in notifications:
                    await self._handle_notification(notification)
                    self._app.state.websocket_bridge_last_notification_id = notification.notification_id
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Websocket bridge polling failed", error=str(exc))
                await asyncio.sleep(self._retry_interval_seconds)

    async def _handle_notification(self, notification: RuntimeNotificationRecord) -> None:
        payload = self._load_payload(notification.payload_json)
        if notification.channel == "agent_response":
            await self._broadcast_agent_response(notification=notification, payload=payload)
            return
        if notification.channel == "turn_ux_plan":
            await self._broadcast_turn_ux_plan(notification=notification, payload=payload)
            return
        if notification.channel == "execution_control":
            await self._broadcast_execution_control(notification=notification, payload=payload)
            return
        if notification.channel == "trace_update":
            await self._broadcast_trace_update(notification=notification)
        if notification.channel == "context_usage":
            await self._broadcast_context_usage(notification=notification, payload=payload)

    async def _broadcast_agent_response(
        self,
        *,
        notification: RuntimeNotificationRecord,
        payload: dict[str, object],
    ) -> None:
        user_id = str(notification.user_id or payload.get("user_id") or "").strip()
        session_id = str(notification.session_id or payload.get("session_id") or "").strip()
        turn_id = str(notification.turn_id or payload.get("turn_id") or "").strip()
        if not user_id:
            return

        response_payload = dict(payload)
        response_payload.setdefault("user_id", user_id)
        response_payload.setdefault("session_id", session_id)
        if turn_id:
            response_payload.setdefault("turn_id", turn_id)
            if "trace_summary" not in response_payload:
                summary = await self._load_trace_summary(user_id=user_id, session_id=session_id, turn_id=turn_id)
                if summary is not None:
                    response_payload["trace_summary"] = summary
                    response_payload["trace_available"] = bool(summary.get("trace_available"))
        await manager.broadcast("agent_response", response_payload, room=f"user_{user_id}")

    async def _broadcast_turn_ux_plan(
        self,
        *,
        notification: RuntimeNotificationRecord,
        payload: dict[str, object],
    ) -> None:
        user_id = str(notification.user_id or payload.get("user_id") or "").strip()
        session_id = str(notification.session_id or payload.get("session_id") or "").strip()
        turn_id = str(notification.turn_id or payload.get("turn_id") or "").strip()
        ux_plan = payload.get("ux_plan")
        if not user_id or not turn_id or not isinstance(ux_plan, dict):
            return

        await manager.broadcast(
            "turn_ux_plan",
            {
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "ux_plan": ux_plan,
            },
            room=f"user_{user_id}",
        )

    async def _broadcast_trace_update(self, *, notification: RuntimeNotificationRecord) -> None:
        user_id = str(notification.user_id or "").strip()
        session_id = str(notification.session_id or "").strip()
        turn_id = str(notification.turn_id or "").strip()
        if not user_id or not session_id or not turn_id:
            return

        summary = await self._load_trace_summary(user_id=user_id, session_id=session_id, turn_id=turn_id)
        if summary is None:
            return

        await manager.broadcast(
            "execution_trace_update",
            {
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "trace_summary": summary,
                "trace_available": bool(summary.get("trace_available")),
            },
            room=f"user_{user_id}",
        )

    async def _broadcast_context_usage(
        self,
        *,
        notification: RuntimeNotificationRecord,
        payload: dict[str, object],
    ) -> None:
        user_id = str(notification.user_id or payload.get("user_id") or "").strip()
        session_id = str(notification.session_id or payload.get("session_id") or "").strip()
        turn_id = str(notification.turn_id or payload.get("turn_id") or "").strip()
        if not user_id or not session_id:
            return

        await manager.broadcast(
            "context_usage",
            {
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "used_tokens": int(payload.get("used_tokens") or 0),
                "window_size": int(payload.get("window_size") or 0),
                "threshold": int(payload.get("threshold") or 0),
            },
            room=f"user_{user_id}",
        )

    async def _broadcast_execution_control(
        self,
        *,
        notification: RuntimeNotificationRecord,
        payload: dict[str, object],
    ) -> None:
        user_id = str(notification.user_id or payload.get("user_id") or "").strip()
        session_id = str(notification.session_id or payload.get("session_id") or "").strip()
        turn_id = str(notification.turn_id or payload.get("turn_id") or "").strip()
        if not user_id or not session_id or not turn_id:
            return

        await manager.broadcast(
            "turn_execution_control",
            {
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "run_id": str(payload.get("run_id") or "").strip() or None,
                "orchestration_id": str(payload.get("orchestration_id") or "").strip() or None,
                "state": str(payload.get("state") or "").strip() or "running",
                "can_cancel": bool(payload.get("can_cancel")),
                "label": str(payload.get("label") or "").strip() or None,
            },
            room=f"user_{user_id}",
        )

    @staticmethod
    def _load_payload(payload_json: str) -> dict[str, object]:
        try:
            payload = json.loads(payload_json or "{}")
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    async def _load_trace_summary(*, user_id: str, session_id: str, turn_id: str) -> dict | None:
        if not user_id or not session_id or not turn_id:
            return None
        try:
            trace_service = get_chat_trace_read_service()
            summary = await trace_service.aget_trace_summary(
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
            )
        except Exception as exc:
            logger.debug(
                "Failed to load trace summary for websocket bridge",
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                error=str(exc),
            )
            return None
        return summary if isinstance(summary, dict) else None
