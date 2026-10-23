"""Recover control-owned question notifications without event-bus delivery guarantees."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

from magi_plugin_sdk.delivery import DeliveryContent
from magi_plugin_sdk.endpoints import EndpointRef

from ..control.ask_delivery import AskDeliveryIntent
from ..control.session_store import ControlSessionStore
from ..delivery.worker import DeliveryWorker
from ..delivery.senders import MessageDeliverySender
from ..events.events import EventTypes
from .ask_outbox import AskDeliveryQueue

logger = logging.getLogger(__name__)


def format_ask_for_channel(
    question: str,
    options: list[str] | tuple[str, ...] | None,
    *,
    hint: str = "（直接回复消息作答即可）",
) -> str:
    """Format a mid-turn question for a plain-text channel message."""
    lines = [(question or "").strip()]
    opts = [str(o).strip() for o in (options or []) if str(o).strip()]
    if opts:
        lines.append("")
        lines.extend(f"{i}. {opt}" for i, opt in enumerate(opts, 1))
    if hint:
        lines.append("")
        lines.append(hint)
    return "\n".join(lines).strip()


class AskFanoutSubscriber:
    """Events wake the worker; the question transaction owns delivery intent."""

    def __init__(self, *, event_bus: Any, session_mapper: Any, channel_registry: Any,
                 session_store: ControlSessionStore, default_user_id: str,
                 delivery_allowed: Callable[[], Awaitable[bool]] | None = None) -> None:
        repository = session_store.ask_delivery_repository
        if repository is None:
            raise RuntimeError("External questions require durable control storage")
        self._bus, self._mapper = event_bus, session_mapper
        self._default_user_id = default_user_id
        self._delivery_allowed = delivery_allowed
        def resolve(channel_id: str):
            channel = channel_registry.get(channel_id)
            return MessageDeliverySender(channel) if channel is not None else None
        self._worker = DeliveryWorker(outbox=AskDeliveryQueue(repository), resolve=resolve)
        self._boundary = asyncio.Lock()
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._sub_id = None
        session_store.bind_ask_delivery_planner(self._plan)

    async def _plan(self, session_id: str, question: str, options: tuple[str, ...]) -> AskDeliveryIntent | None:
        mapping = await self._mapper.lookup_by_session(session_id)
        if mapping is None:
            return None
        connection, separator, contribution = mapping.channel_type.partition(":")
        endpoint = EndpointRef(connection if separator else None,
            contribution if separator else connection, mapping.external_chat_id, mapping.external_thread_id)
        if endpoint.registry_key == "chat_sse":
            return None
        return AskDeliveryIntent(mapping.magi_user_id or self._default_user_id, endpoint,
                                 DeliveryContent(text=format_ask_for_channel(question, options)))

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(EventTypes.CONTROL_ASK_REQUESTED, self._on_ask_requested)
        self._task = asyncio.create_task(self._run(), name="question-delivery-recovery")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._sub_id is not None:
            await self._bus.unsubscribe(self._sub_id)
            self._sub_id = None

    async def _on_ask_requested(self, event: Any) -> None:
        # No event payload is trusted as a delivery command.
        self._wake.set()

    @asynccontextmanager
    async def conversation_clear_boundary(self) -> AsyncIterator[None]:
        async with self._boundary:
            yield

    async def drain(self) -> None:
        while await self.run_once():
            await asyncio.sleep(0)

    async def run_once(self) -> bool:
        async with self._boundary:
            if self._delivery_allowed is not None and not await self._delivery_allowed():
                return False
            return await self._worker.run_once()

    async def _run(self) -> None:
        while True:
            self._wake.clear()
            try:
                if await self.run_once():
                    await asyncio.sleep(0)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Question delivery recovery failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
