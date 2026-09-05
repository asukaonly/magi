"""Source hub: aggregates source events into a unified queue."""

from __future__ import annotations

import asyncio
from typing import Optional

from ..core.logger import get_logger
from ..events.backend import MessageBusBackend
from ..events.events import Event, EventTypes
from ..identity import canonicalize_user_id as _canonicalize_user_id
from ..core.runtime_namespace import DEFAULT_RUNTIME_NAMESPACE
from .contracts import SourceEvent

logger = get_logger(__name__)


class SourceHub:
    """Collects events from sources and exposes batched reads for router agent."""

    def __init__(self, message_bus: MessageBusBackend) -> None:
        self._message_bus = message_bus
        self._subscription_id: Optional[str] = None
        self._queue: asyncio.Queue[SourceEvent] = asyncio.Queue()
        self._queue_mutation_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._subscription_id:
            return
        self._subscription_id = await self._message_bus.subscribe(
            EventTypes.USER_MESSAGE,
            self._on_user_message,
            propagation_mode="broadcast",
        )
        logger.info("SourceHub subscribed to USER_MESSAGE")

    async def stop(self) -> None:
        if not self._subscription_id:
            return
        await self._message_bus.unsubscribe(self._subscription_id)
        self._subscription_id = None
        logger.info("SourceHub unsubscribed from USER_MESSAGE")

    async def push_source_event(self, source_event: SourceEvent) -> None:
        async with self._queue_mutation_lock:
            self._queue.put_nowait(source_event)

    async def get_batch(
        self, max_items: int = 16, timeout_seconds: float = 0.2
    ) -> list[SourceEvent]:
        batch: list[SourceEvent] = []
        try:
            first = await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return batch

        batch.append(first)
        async with self._queue_mutation_lock:
            while len(batch) < max_items:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
        return batch

    async def discard_stale_user_messages(self, current_generation: int) -> int:
        """Remove queued user messages from generations older than a clear boundary."""
        discarded = 0
        retained: list[SourceEvent] = []
        async with self._queue_mutation_lock:
            while True:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item.event_type == EventTypes.USER_MESSAGE and (
                    item.user_message_generation is None
                    or int(item.user_message_generation) < int(current_generation)
                ):
                    discarded += 1
                    continue
                retained.append(item)
            for item in retained:
                self._queue.put_nowait(item)
        return discarded

    async def discard_user_message_scope(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None = None,
        message_id: str | None = None,
    ) -> int:
        """Remove queued user messages for one durably deleted chat scope."""
        normalized_user_id = str(user_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        normalized_message_id = str(message_id or "").strip()
        discarded = 0
        retained: list[SourceEvent] = []
        async with self._queue_mutation_lock:
            while True:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if _matches_user_message_scope(
                    item,
                    user_id=normalized_user_id,
                    session_id=normalized_session_id,
                    turn_id=normalized_turn_id,
                    message_id=normalized_message_id,
                ):
                    discarded += 1
                    continue
                retained.append(item)
            for item in retained:
                self._queue.put_nowait(item)
        return discarded

    async def _on_user_message(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        content = str(data.get("content") or "").strip()
        attachments = data.get("attachments") if isinstance(data.get("attachments"), list) else []
        if not content:
            if not attachments:
                return

        session_id = str(data.get("session_id") or "").strip()

        source_event = SourceEvent(
            source_name="user_input_source",
            event_type=EventTypes.USER_MESSAGE,
            payload={
                "content": content,
                "attachments": list(attachments),
                # Phase H+2 identity layer ingress #3: canonicalize the
                # user_id from the bus payload so any channel-prefixed
                # leaker (legacy fact, stale producer) gets collapsed to
                # the canonical MagiUserID before reaching memory L1.
                # Today this is mostly a no-op (session_mapper hands
                # canonical values upstream), but the assertion makes
                # the invariant explicit at the awareness boundary.
                "user_id": str(_canonicalize_user_id(data.get("user_id"))),
                "runtime_namespace": str(
                    data.get("runtime_namespace")
                    or (data.get("metadata") or {}).get("runtime_namespace")
                    or DEFAULT_RUNTIME_NAMESPACE
                ),
                "session_id": session_id,
                "turn_id": str(data.get("turn_id") or "").strip() or None,
                "workspace_path": str(data.get("workspace_path") or "").strip() or None,
                "metadata": data.get("metadata") or {},
                "timestamp": float(data.get("timestamp") or event.timestamp),
                # Phase H+1 plumbing: ``UserMessagePayload.from_dict`` reads
                # this to tag the resulting ``RunTrigger.source_channel``
                # (api → user_message; telegram/weixin → external_inbound).
                # Without this, the external channel scheme set by the
                # dispatcher (e.g. "weixin") is silently dropped here and
                # downstream defaults to "api", which the trigger then maps
                # to chat_sse — so reply-via-origin-channel never fires for
                # any external inbound. Defaults to "api" to preserve
                # legacy behavior for events that genuinely lack a source.
                "source": str(data.get("source") or "api"),
            },
            timestamp=float(data.get("timestamp") or event.timestamp),
            correlation_id=event.correlation_id,
            user_message_generation=(
                int(data["user_message_generation"])
                if data.get("user_message_generation") is not None
                else None
            ),
            delivery_attempt_no=(
                int(data["delivery_attempt_no"])
                if data.get("delivery_attempt_no") is not None
                else None
            ),
            runtime_command_id=(
                int(data["runtime_command_id"])
                if data.get("runtime_command_id") is not None
                else None
            ),
        )
        await self.push_source_event(source_event)


def _user_message_id_from_correlation(correlation_id: str | None) -> str:
    normalized = str(correlation_id or "").strip()
    prefix = "user_message:"
    return normalized[len(prefix) :].strip() if normalized.startswith(prefix) else ""


def _matches_user_message_scope(
    item: SourceEvent,
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    message_id: str,
) -> bool:
    if item.event_type != EventTypes.USER_MESSAGE:
        return False
    payload = item.payload if isinstance(item.payload, dict) else {}
    if str(payload.get("user_id") or "").strip() != user_id:
        return False
    if str(payload.get("session_id") or "").strip() != session_id:
        return False
    if not turn_id and not message_id:
        return True
    if turn_id and str(payload.get("turn_id") or "").strip() == turn_id:
        return True
    return bool(
        message_id and _user_message_id_from_correlation(item.correlation_id) == message_id
    )
