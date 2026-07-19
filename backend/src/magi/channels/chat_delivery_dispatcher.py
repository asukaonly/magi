"""Channel-owned delivery dispatcher for chat task-agent egress."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from magi.config import get_user_preference
from magi.llm.streaming_events import LLMStreamEvent
from magi_plugin_sdk.delivery import DeliveryChunk, DeliveryContent

from ..core.logger import get_logger
from ..delivery.contracts import DeliveryFanoutResult
from .delivery_prefs import resolve_delivery_targets
from .delivery_router import (
    ChannelRegistryProtocol,
    DeliveryRouter,
)

logger = get_logger(__name__)

UserPrefsProvider = Callable[[str], Awaitable[dict[str, Any]]]


async def read_configured_delivery_prefs(user_id: str) -> dict[str, Any]:
    """Read configured delivery-channel preferences for one user."""
    _ = user_id
    channels = get_user_preference("delivery_channels", None)
    if isinstance(channels, list) and channels:
        return {"delivery_channels": list(channels)}
    return {}


class ChatDeliveryDispatcher:
    """Dispatch chat responses through channel-owned delivery infrastructure."""

    def __init__(
        self,
        *,
        delivery_router: DeliveryRouter,
        user_prefs_provider: UserPrefsProvider | None = None,
        receipts_store: Any | None = None,
    ) -> None:
        self._delivery_router = delivery_router
        self._user_prefs_provider = user_prefs_provider
        self._receipts_store = receipts_store

    @classmethod
    def from_registry(
        cls,
        *,
        channel_registry: ChannelRegistryProtocol,
        user_prefs_provider: UserPrefsProvider | None = None,
        receipts_store: Any | None = None,
    ) -> "ChatDeliveryDispatcher":
        return cls(
            delivery_router=DeliveryRouter(channel_registry=channel_registry),
            user_prefs_provider=user_prefs_provider,
            receipts_store=receipts_store,
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

        user_prefs = await self._resolve_user_prefs(user_id)
        ctx_prefs = getattr(context, "user_prefs", None)
        if isinstance(ctx_prefs, dict):
            user_prefs = {**user_prefs, **ctx_prefs}

        origin_channel: str | None = None
        active_run = getattr(context, "active_run", None)
        if active_run is not None:
            trigger = getattr(active_run, "trigger", None)
            if trigger is not None:
                origin_channel = getattr(trigger, "source_channel", None)

        targets = resolve_delivery_targets(
            user_id=user_id,
            session_id=session_id,
            user_prefs=user_prefs,
            origin_channel=origin_channel,
        )
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
        if not targets:
            return DeliveryFanoutResult()

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
        result = await self._delivery_router.fanout_deliver(
            content=delivery_content,
            targets=targets,
        )
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
        user_prefs = await self._resolve_user_prefs(user_id)
        targets = resolve_delivery_targets(
            user_id=user_id,
            session_id=session_id,
            user_prefs=user_prefs,
        )
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
        if self._receipts_store is None or not session_id or not run_id:
            return
        try:
            receipts = await self._receipts_store.list_receipts(
                session_id=session_id,
                run_id=run_id,
            )
        except Exception:
            logger.warning(
                "DeliveryReceiptsStore.list_receipts failed",
                exc_info=True,
            )
            return
        if not receipts:
            return
        try:
            await self._delivery_router.fanout_retract(receipts=receipts)
        except Exception:
            logger.warning(
                "DeliveryRouter.fanout_retract failed",
                exc_info=True,
            )

    async def _resolve_user_prefs(self, user_id: str) -> dict[str, Any]:
        if self._user_prefs_provider is None or not user_id:
            return {}
        try:
            extra = await self._user_prefs_provider(user_id)
        except Exception as exc:
            logger.debug("user_prefs_provider raised, defaulting to empty prefs: %s", exc)
            return {}
        return dict(extra or {})


__all__ = [
    "ChatDeliveryDispatcher",
    "read_configured_delivery_prefs",
]
