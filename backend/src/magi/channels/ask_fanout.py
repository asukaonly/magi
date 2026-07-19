"""External-channel fanout for control ask events."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent

from ..control.common import events as control_events
from ..events.domain_payloads import ControlAskRequested
from ..events.events import Event, EventTypes
from ..events.payload_helpers import PayloadTypeError, expect_payload
from ..delivery.contracts import DeliveryFanoutResult

logger = logging.getLogger(__name__)

ASK_DEDUP_MAX_ENTRIES = 4096
ASK_DEDUP_MIN_RETENTION_SECONDS = 60.0


class AskChannelDeliveryError(RuntimeError):
    """Raised when an external ask cannot be confirmed as delivered."""

    def __init__(
        self,
        message: str,
        *,
        result: DeliveryFanoutResult | None = None,
    ) -> None:
        self.result = result
        super().__init__(message)


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
) -> DeliveryFanoutResult | None:
    """Resolve the session's origin channel and deliver the question to it."""
    if not session_id or session_mapper is None or delivery_router is None:
        return None
    try:
        mapping = await session_mapper.lookup_by_session(session_id)
    except Exception as exc:  # noqa: BLE001
        raise AskChannelDeliveryError(
            f"Ask channel lookup failed for session {session_id!r}: {exc}"
        ) from exc
    origin_channel = getattr(mapping, "channel_type", None) if mapping else None
    targets = build_ask_fanout_targets(
        session_id=session_id,
        user_id=str(user_id or default_user_id),
        origin_channel=origin_channel,
    )
    if not targets:
        return None
    try:
        result = await delivery_router.fanout_deliver(
            content=DeliveryContent(text=format_ask_for_channel(question, options)),
            targets=targets,
        )
    except Exception as exc:  # noqa: BLE001
        raise AskChannelDeliveryError(
            f"Ask delivery failed for channel {targets[0].channel_type!r}: {exc}"
        ) from exc
    if result.failures or len(result.receipts) != 1:
        failure_details = "; ".join(
            str(failure.error) for failure in result.failures
        )
        detail = failure_details or (
            f"expected one receipt, received {len(result.receipts)}"
        )
        raise AskChannelDeliveryError(
            f"Ask delivery failed for channel {targets[0].channel_type!r}: {detail}",
            result=result,
        )
    return result


class AskFanoutSubscriber:
    """Deliver pending control ask events to the originating external channel."""

    def __init__(
        self,
        *,
        event_bus: Any,
        session_mapper: Any,
        delivery_router: Any,
        default_user_id: str,
        max_dedup_entries: int = ASK_DEDUP_MAX_ENTRIES,
        now_seconds: Callable[[], float] | None = None,
        delivery_allowed: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        if max_dedup_entries <= 0:
            raise ValueError("Ask fanout dedup capacity must be positive")
        self._bus = event_bus
        self._session_mapper = session_mapper
        self._delivery_router = delivery_router
        self._default_user_id = default_user_id
        self._sub_id: str | None = None
        self._inflight: set[asyncio.Task[Any]] = set()
        self._recent_request_ids: OrderedDict[str, float] = OrderedDict()
        self._max_dedup_entries = int(max_dedup_entries)
        self._now_seconds = now_seconds or time.time
        self._delivery_allowed = delivery_allowed
        self._delivery_boundary_lock = asyncio.Lock()

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
        self._recent_request_ids.clear()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    @asynccontextmanager
    async def conversation_clear_boundary(self) -> AsyncIterator[None]:
        """Wait for active ask delivery and block new delivery during a clear."""

        async with self._delivery_boundary_lock:
            yield

    async def _on_ask_requested(self, event: Event) -> None:
        try:
            payload = expect_payload(event, ControlAskRequested)
        except PayloadTypeError:
            logger.exception("malformed ControlAskRequested payload")
            return

        if getattr(payload.ask, "status", None) != "pending":
            return
        request_id = str(getattr(payload.ask, "request_id", "") or "").strip()
        if not request_id:
            logger.warning("ask_fanout.missing_request_id")
            return
        expires_at = float(getattr(payload.ask, "expires_at", 0.0) or 0.0)
        if expires_at > 0 and expires_at <= float(self._now_seconds()):
            return
        if not self._remember_request_id(
            request_id,
            expires_at=expires_at,
        ):
            return

        task = asyncio.create_task(
            self._deliver_once(payload),
            name=f"ask-channel-delivery-{request_id}",
        )
        self._inflight.add(task)
        task.add_done_callback(self._on_delivery_done)

    def _remember_request_id(
        self,
        request_id: str,
        *,
        expires_at: float,
    ) -> bool:
        """Reserve one bounded, expiring process-local delivery identity."""

        now = float(self._now_seconds())
        if expires_at > 0.0 and expires_at <= now:
            return False
        expired = [
            existing_request_id
            for existing_request_id, retain_until in self._recent_request_ids.items()
            if retain_until <= now
        ]
        for existing_request_id in expired:
            self._recent_request_ids.pop(existing_request_id, None)

        if request_id in self._recent_request_ids:
            self._recent_request_ids.move_to_end(request_id)
            return False

        retain_until = max(
            float(expires_at),
            now + ASK_DEDUP_MIN_RETENTION_SECONDS,
        )
        self._recent_request_ids[request_id] = retain_until
        while len(self._recent_request_ids) > self._max_dedup_entries:
            self._recent_request_ids.popitem(last=False)
        return True

    async def _deliver_once(self, payload: ControlAskRequested) -> None:
        """Attempt once because a missing receipt does not prove non-delivery."""

        async with self._delivery_boundary_lock:
            if (
                self._delivery_allowed is not None
                and not await self._delivery_allowed()
            ):
                return
            try:
                await deliver_ask_to_channel(
                    session_id=payload.session_id,
                    user_id=payload.user_id,
                    question=payload.ask.question,
                    options=payload.ask.options,
                    session_mapper=self._session_mapper,
                    delivery_router=self._delivery_router,
                    default_user_id=self._default_user_id,
                )
            except AskChannelDeliveryError as exc:
                await control_events.publish_control_event(
                    "control.ask.delivery_failed",
                    {
                        "request_id": payload.ask.request_id,
                        "session_id": payload.session_id,
                        "error": str(exc),
                        "delivery_attempts": 1,
                        "automatic_retry": False,
                    },
                    session_id=payload.session_id,
                    user_id=payload.user_id,
                    turn_id=payload.turn_id,
                )
                raise

    def _on_delivery_done(self, task: asyncio.Task[Any]) -> None:
        self._inflight.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.warning(
                "ask_fanout.delivery_exhausted: %s",
                error,
                exc_info=(type(error), error, error.__traceback__),
            )


__all__ = [
    "AskChannelDeliveryError",
    "AskFanoutSubscriber",
    "build_ask_fanout_targets",
    "deliver_ask_to_channel",
    "format_ask_for_channel",
]
