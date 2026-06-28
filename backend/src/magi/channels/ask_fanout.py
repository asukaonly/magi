"""External-channel fanout for control ask events."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent

from ..events.domain_payloads import ControlAskRequested
from ..events.events import Event, EventTypes
from ..events.payload_helpers import PayloadTypeError, expect_payload

logger = logging.getLogger(__name__)


def build_ask_fanout_targets(
    *,
    session_id: str | None,
    user_id: str,
    origin_channel: str | None,
) -> list[ChannelTarget]:
    """Compute channel targets for an ask fanout."""
    if not session_id:
        return []
    normalized = (origin_channel or "").strip()
    if not normalized or normalized == "chat_sse":
        return []
    return [
        ChannelTarget(
            channel_type=normalized,
            external_chat_id="",
            magi_session_id=session_id,
            magi_user_id=user_id,
        )
    ]


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


async def deliver_ask_to_channel(
    *,
    session_id: str,
    user_id: str | None,
    question: str,
    options: list[str] | tuple[str, ...],
    session_mapper: Any,
    delivery_router: Any,
    default_user_id: str,
) -> None:
    """Resolve the session's origin channel and deliver the question to it."""
    if not session_id or session_mapper is None or delivery_router is None:
        return
    try:
        mapping = await session_mapper.lookup_by_session(session_id)
    except Exception:  # noqa: BLE001
        logger.debug("ask_fanout.session_lookup_failed", exc_info=True)
        return
    origin_channel = getattr(mapping, "channel_type", None) if mapping else None
    targets = build_ask_fanout_targets(
        session_id=session_id,
        user_id=str(user_id or default_user_id),
        origin_channel=origin_channel,
    )
    if not targets:
        return
    try:
        await delivery_router.fanout_deliver(
            content=DeliveryContent(
                text=format_ask_for_channel(question, options)
            ),
            targets=targets,
        )
    except Exception:  # noqa: BLE001
        logger.debug("ask_fanout.deliver_failed", exc_info=True)


class AskFanoutSubscriber:
    """Deliver pending control ask events to the originating external channel."""

    def __init__(
        self,
        *,
        event_bus: Any,
        session_mapper: Any,
        delivery_router: Any,
        default_user_id: str,
    ) -> None:
        self._bus = event_bus
        self._session_mapper = session_mapper
        self._delivery_router = delivery_router
        self._default_user_id = default_user_id
        self._sub_id: str | None = None
        self._inflight: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(
            EventTypes.CONTROL_ASK_REQUESTED,
            self._on_ask_requested,
        )

    async def stop(self) -> None:
        if self._sub_id is not None:
            try:
                await self._bus.unsubscribe(self._sub_id)
            except Exception:
                logger.exception("ask_fanout.unsubscribe_failed")
            self._sub_id = None
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def _on_ask_requested(self, event: Event) -> None:
        try:
            payload = expect_payload(event, ControlAskRequested)
        except PayloadTypeError:
            logger.exception("malformed ControlAskRequested payload")
            return

        if getattr(payload.ask, "status", None) != "pending":
            return

        task = asyncio.create_task(
            deliver_ask_to_channel(
                session_id=payload.session_id,
                user_id=payload.user_id,
                question=payload.ask.question,
                options=payload.ask.options,
                session_mapper=self._session_mapper,
                delivery_router=self._delivery_router,
                default_user_id=self._default_user_id,
            )
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)


__all__ = [
    "AskFanoutSubscriber",
    "build_ask_fanout_targets",
    "deliver_ask_to_channel",
    "format_ask_for_channel",
]

