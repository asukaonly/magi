"""ChatSseChannel — wraps the existing chat SSE emission path as a
first-class ``Channel`` so the same ``DeliveryRouter`` handles SSE
delivery alongside Telegram/Weixin/future channels.

Phase G scope: thin wrapper. Phase I will deepen with multi-modal
ContentBlock streaming.

The constructor takes an ``emit_to_chat`` callable that adapts the
underlying chat event emission mechanism. The default callable
(injected by ChatTaskAgent or PluginManager during registration)
publishes to the appropriate event bus / stream sink. Tests inject
their own callable.
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from magi_plugin_sdk.channels import Channel, ChannelTarget, OutboundContent
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt


# Callable signature: (session_id, payload) -> external_message_id
EmitToChat = Callable[[str, dict[str, Any]], Awaitable[str]]


async def _default_emit(session_id: str, payload: dict[str, Any]) -> str:
    """Default emitter used when none is injected. Logs and returns
    a synthetic id — production wires a real emitter via __init__."""
    from ..core.logger import get_logger
    logger = get_logger(__name__)
    logger.info("ChatSseChannel default emit (no emitter wired): session=%s payload=%s",
                session_id, payload)
    return f"synthetic_{int(time.time() * 1000)}"


class ChatSseChannel(Channel):
    """Host-internal Channel for chat SSE delivery.

    Uses ``channel_type`` as a composite identifier in the form
    ``"chat_sse:<session_id>"``. The session_id is extracted from this
    composite when routing to the correct SSE stream.
    """

    supports_streaming = True
    supports_attachments = True
    supports_revision = False  # SSE renders are immutable in current UI

    CHANNEL_TYPE = "chat_sse"

    def __init__(self, *, emit_to_chat: EmitToChat | None = None) -> None:
        self._emit = emit_to_chat or _default_emit

    @property
    def channel_type(self) -> str:
        return self.CHANNEL_TYPE

    async def start(self) -> None:
        """No-op — SSE channel is always live via the HTTP server."""
        return None

    async def stop(self) -> None:
        """No-op — SSE channel lifecycle managed by HTTP server."""
        return None

    async def send_message(self, target: ChannelTarget, content: OutboundContent) -> None:
        """Legacy path — used by existing NotificationRelay flow."""
        session_id = self._extract_session_id(target.channel_type)
        await self._emit(session_id, {"text": content.text})

    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        # Phase G: no-op. Frontend already shows typing indicator from streaming chunks.
        return None

    async def deliver(
        self,
        target: ChannelTarget,
        content: DeliveryContent,
    ) -> DeliveryReceipt:
        """Phase G delivery returning a DeliveryReceipt."""
        session_id = self._extract_session_id(target.channel_type)
        payload: dict[str, Any] = {
            "text": content.text,
            "formatting": content.formatting,
        }
        if content.attachments:
            payload["attachments"] = [dict(a) for a in content.attachments]
        external_id = await self._emit(session_id, payload)
        return DeliveryReceipt(
            channel_id=target.channel_type,
            external_message_id=external_id,
            delivered_at_ms=int(time.time() * 1000),
        )

    # revise/retract intentionally not overridden — defaults raise NotImplementedError
    # because the chat UI today doesn't model message edits / deletes. Phase F+
    # ConversationLog event-sourcing will make these meaningful.

    @staticmethod
    def _extract_session_id(channel_type: str) -> str:
        """``chat_sse:<session_id>`` → ``<session_id>``."""
        if channel_type.startswith("chat_sse:"):
            return channel_type[len("chat_sse:"):]
        return channel_type


__all__ = ["ChatSseChannel", "EmitToChat"]
