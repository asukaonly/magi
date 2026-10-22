"""Channel-owned delivery dispatcher for chat task-agent egress."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
import time
from typing import Any, AsyncIterator, AsyncContextManager

from magi.config import get_user_preference
from magi.llm.streaming_events import LLMStreamEvent
from magi_plugin_sdk.delivery import DeliveryChunk, DeliveryContent

from ..core.logger import get_logger
from ..delivery.contracts import DeliveryFailure, DeliveryFanoutResult
from ..delivery.outbox import DeliveryOutbox
from magi_plugin_sdk.channels import ChannelTarget
from ..delivery.routing import DeliveryPlan, build_delivery_plan
from .delivery_router import (
    ChannelRegistryProtocol,
    DeliveryRouter,
)

logger = get_logger(__name__)

UserPrefsProvider = Callable[[str], Awaitable[dict[str, Any]]]


@asynccontextmanager
async def _unscoped_boundary() -> AsyncIterator[None]:
    yield



async def read_configured_delivery_prefs(user_id: str) -> dict[str, Any]:
    """Read configured delivery-channel preferences for one user."""
    _ = user_id
    targets = get_user_preference("delivery_targets", None)
    if targets is None:
        if get_user_preference("delivery_channels", None):
            raise ValueError("Configure explicit delivery targets before using scheme-only preferences")
        targets = []
    if not isinstance(targets, list):
        raise ValueError("Delivery preferences require explicit endpoint references")
    return {"delivery_targets": list(targets)}


class ChatDeliveryDispatcher:
    """Dispatch chat responses through channel-owned delivery infrastructure."""

    def __init__(
        self,
        *,
        delivery_router: DeliveryRouter,
        user_prefs_provider: UserPrefsProvider | None = None,
        receipts_store: Any | None = None,
        outbox: DeliveryOutbox | None = None,
        notify_outbound: Callable[[], None] | None = None,
        delivery_boundary: Callable[[], AsyncContextManager[None]] = _unscoped_boundary,
    ) -> None:
        self._delivery_router = delivery_router
        self._user_prefs_provider = user_prefs_provider
        self._receipts_store = receipts_store
        self._outbox = outbox
        self._notify_outbound = notify_outbound
        self._delivery_boundary = delivery_boundary

    @classmethod
    def from_registry(
        cls,
        *,
        channel_registry: ChannelRegistryProtocol,
        user_prefs_provider: UserPrefsProvider | None = None,
        receipts_store: Any | None = None,
        outbox: DeliveryOutbox | None = None,
        notify_outbound: Callable[[], None] | None = None,
        delivery_boundary: Callable[[], AsyncContextManager[None]] = _unscoped_boundary,
    ) -> "ChatDeliveryDispatcher":
        return cls(
            delivery_router=DeliveryRouter(channel_registry=channel_registry),
            user_prefs_provider=user_prefs_provider,
            receipts_store=receipts_store,
            outbox=outbox, notify_outbound=notify_outbound, delivery_boundary=delivery_boundary,
        )

    async def resolve_delivery_plan(self, context: Any) -> DeliveryPlan:
        user_prefs = await self._resolve_user_prefs(context.user_id)
        context_prefs = getattr(context, "user_prefs", None)
        if isinstance(context_prefs, dict):
            user_prefs = {**user_prefs, **context_prefs}
        trigger = getattr(getattr(context, "active_run", None), "trigger", None)
        ingress = getattr(trigger, "ingress", None)
        return build_delivery_plan(
            session_id=context.session_id, user_id=context.user_id, user_prefs=user_prefs,
            reply_to=ingress.reply_to if ingress is not None else None,
        )

    async def deliver_final_response(
        self,
        request: Any,
        *,
        response_text: str,
        attachments: Any = (),
        content: DeliveryContent | None = None,
        exclude_chat_sse: bool = False,
        chat_sse_only: bool = False,
        exclude_channel_types: Iterable[str] = (),
    ) -> DeliveryFanoutResult:
        """Deliver a final assistant response to configured channel targets."""
        context = getattr(request, "context", None)
        session_id = getattr(context, "session_id", "") or ""
        session_run_id = getattr(context, "session_run_id", "") or ""
        user_id = getattr(context, "user_id", "") or ""

        # External destinations were frozen with the accepted message transaction.
        # Native conversation notifications remain hints over durable chat state.
        targets = [ChannelTarget("chat_sse", "", magi_session_id=session_id, magi_user_id=user_id)]
        if exclude_chat_sse:
            targets = [target for target in targets if target.channel_type != "chat_sse"]
        if chat_sse_only:
            targets = [target for target in targets if target.channel_type == "chat_sse"]
        excluded_channel_types = {
            str(channel_type or "").strip()
            for channel_type in exclude_channel_types
            if str(channel_type or "").strip()
        }
        if excluded_channel_types:
            targets = [
                target
                for target in targets
                if target.channel_type not in excluded_channel_types
            ]

        delivery_content = content if content is not None else DeliveryContent(
            text=response_text or "",
            attachments=tuple(attachments or ()),
        )
        logger.info(
            "fanout_to_origin_channels text_len=%d attachments=%d targets=%s",
            len(delivery_content.text or ""),
            len(delivery_content.attachments or ()),
            [target.channel_type for target in targets],
        )
        result = await self._delivery_router.fanout_deliver(content=delivery_content, targets=targets)
        if not chat_sse_only and delivery_content.message_id and self._outbox is not None:
            deliveries = await self._outbox.list_outbound_deliveries(message_id=delivery_content.message_id)
            receipts = list(result.receipts)
            failures = list(result.failures)
            pending = []
            for item in deliveries:
                if item.receipt is not None:
                    receipts.append(item.receipt)
                elif item.state in {"pending", "leased", "sending"}:
                    pending.append(item.endpoint)
                elif item.state in {"failed", "uncertain"}:
                    target = DeliveryPlan(session_id, user_id, (item.endpoint,)).channel_targets()[0]
                    failures.append(DeliveryFailure(target, RuntimeError(f"Delivery {item.state}"), item.attempt_count > 0))
            if pending and self._notify_outbound is not None:
                self._notify_outbound()
            result = DeliveryFanoutResult(tuple(receipts), tuple(failures), tuple(pending))
        if (
            result.receipts
            and self._receipts_store is not None
            and session_id
            and session_run_id
        ):
            try:
                await self._receipts_store.save_receipts(
                    session_id=session_id,
                    run_id=session_run_id,
                    revision=int(context.session_run_revision or 0),
                    receipts=list(result.receipts),
                )
            except Exception:
                logger.warning(
                    "DeliveryReceiptsStore.save_receipts failed",
                    exc_info=True,
                )
        return result

    async def dispatch_stream_chunk(
        self,
        *,
        session_id: str,
        user_id: str,
        text: str,
        is_final: bool,
        seq: int,
        turn_id: str | None = None,
        event: LLMStreamEvent | None = None,
        persona_id: str | None = None,
    ) -> None:
        """Stream one chunk to configured channel targets."""
        if not session_id:
            return
        targets = [ChannelTarget("chat_sse", "", magi_session_id=session_id, magi_user_id=user_id)]
        await self._delivery_router.fanout_chunk(
            chunk=DeliveryChunk(
                text=text,
                is_final=is_final,
                seq=seq,
                turn_id=turn_id,
                event=event.to_wire_dict() if event is not None else None,
                persona_id=persona_id,
            ),
            targets=targets,
        )

    async def retract_run_deliveries(
        self,
        *,
        session_id: str,
        run_id: str,
    ) -> None:
        """Retract messages previously delivered for one chat run."""
        if not session_id or not run_id:
            return
        async with self._delivery_boundary():
            receipts = []
            if self._outbox is not None:
                await self._outbox.cancel_run_outbound_deliveries(
                    session_id=session_id, run_id=run_id, now_ms=int(time.time()*1000),
                )
                receipts.extend(item.receipt for item in await self._outbox.list_run_outbound_deliveries(
                    session_id=session_id, run_id=run_id,
                ) if item.receipt is not None)
            if self._receipts_store is not None:
                receipts.extend(await self._receipts_store.list_receipts(session_id=session_id, run_id=run_id))
            unique = { (r.channel_id, r.external_message_id, r.magi_session_id): r for r in receipts }
            if unique:
                await self._delivery_router.fanout_retract(receipts=list(unique.values()))

    async def _resolve_user_prefs(self, user_id: str) -> dict[str, Any]:
        if self._user_prefs_provider is None or not user_id:
            return {}
        extra = await self._user_prefs_provider(user_id)
        return dict(extra or {})



__all__ = [
    "ChatDeliveryDispatcher",
    "read_configured_delivery_prefs",
]
