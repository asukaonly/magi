"""Notification relay — polls Magi notifications and delivers them to channels."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ..core.logger import get_logger
from ..runtime_trace import RuntimeNotificationRecord, RuntimeTraceStore
from .base import Channel
from .contracts import ChannelTarget, OutboundContent
from .registry import ChannelRegistry
from .session_mapper import ChannelSessionMapper

logger = get_logger(__name__)

# Notification channels that carry response content for external delivery.
_RESPONSE_CHANNELS = frozenset({"agent_response", "agent_response_chunk"})


class NotificationRelay:
    """Polls Magi notifications and relays agent responses to external channels."""

    def __init__(
        self,
        *,
        registry: ChannelRegistry,
        session_mapper: ChannelSessionMapper,
        trace_store: RuntimeTraceStore,
        poll_interval_s: float = 0.5,
    ) -> None:
        self._registry = registry
        self._session_mapper = session_mapper
        self._trace_store = trace_store
        self._poll_interval_s = poll_interval_s
        self._running = False
        self._cursor: int = 0
        # Accumulate streaming deltas per (session_id, turn_id)
        self._chunk_buffers: dict[tuple[str, str], list[str]] = {}

    async def run(self) -> None:
        self._running = True
        self._cursor = await self._trace_store.get_latest_notification_id()
        logger.info("Notification relay started", cursor=self._cursor)
        while self._running:
            try:
                await self._poll_cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Notification relay poll error")
            await asyncio.sleep(self._poll_interval_s)
        logger.info("Notification relay stopped")

    def stop(self) -> None:
        self._running = False

    async def _poll_cycle(self) -> None:
        notifications = await self._trace_store.list_notifications(
            after_id=self._cursor, limit=100
        )
        for notif in notifications:
            self._cursor = max(self._cursor, notif.notification_id)
            if notif.channel not in _RESPONSE_CHANNELS:
                continue
            await self._dispatch_notification(notif)

    async def _dispatch_notification(self, notif: RuntimeNotificationRecord) -> None:
        mapping = await self._session_mapper.lookup_by_session(notif.session_id)
        if mapping is None:
            return  # Not a channel-owned session

        channel = self._registry.get(mapping.channel_type)
        if channel is None:
            return

        target = ChannelTarget(
            channel_type=mapping.channel_type,
            external_chat_id=mapping.external_chat_id,
        )

        try:
            payload: dict[str, Any] = json.loads(notif.payload_json)
        except (json.JSONDecodeError, TypeError):
            return

        if notif.channel == "agent_response":
            content_text = str(payload.get("content") or "")
            if not content_text.strip():
                return
            await self._send_with_retry(
                channel, target, OutboundContent(text=content_text, is_final=True)
            )
        elif notif.channel == "agent_response_chunk":
            turn_id = payload.get("turn_id") or ""
            buf_key = (notif.session_id, turn_id)
            delta = str(payload.get("content_delta") or "")

            if not payload.get("is_final"):
                # Accumulate streaming delta
                if delta:
                    self._chunk_buffers.setdefault(buf_key, []).append(delta)
                return

            # is_final — assemble full response from accumulated deltas
            parts = self._chunk_buffers.pop(buf_key, [])
            if delta:
                parts.append(delta)
            content_text = "".join(parts)
            if not content_text.strip():
                return
            logger.debug(
                "Delivering assembled streamed response",
                session_id=notif.session_id,
                turn_id=turn_id,
                chars=len(content_text),
            )
            await self._send_with_retry(
                channel, target, OutboundContent(text=content_text, is_final=True)
            )

    async def _send_with_retry(
        self,
        channel: Channel,
        target: ChannelTarget,
        content: OutboundContent,
        max_retries: int = 2,
    ) -> None:
        for attempt in range(max_retries + 1):
            try:
                await channel.send_message(target, content)
                return
            except Exception:
                if attempt == max_retries:
                    logger.exception(
                        "Failed to deliver message to channel",
                        channel_type=target.channel_type,
                        external_chat_id=target.external_chat_id,
                    )
                else:
                    await asyncio.sleep(0.5 * (attempt + 1))
