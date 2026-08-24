"""ChatSseChannel — wraps the chat UI's runtime_trace notification bus as
a first-class ``Channel`` so the same ``DeliveryRouter`` handles SSE
delivery alongside Telegram/Weixin/future channels.

Phase G+1: the chat UI's SSE bus is the ``runtime_trace_store`` notification
table — chat frontends poll it for ``agent_response`` (final assembled reply)
and ``agent_response_chunk`` (streaming text deltas) records. When a
``trace_store`` is wired into this channel, ``deliver``/``deliver_chunk``
append the ``agent_response`` / ``agent_response_chunk`` rows directly there.
Since the P3 convergence, this channel is the sole writer of those rows.

Backward compat: the legacy ``emit_to_chat`` callable still works when
``trace_store=None``. Both may be set independently.

Phase I will deepen with multi-modal ContentBlock streaming.
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from magi_plugin_sdk.channels import (
    Channel,
    ChannelInboundClearStrategy,
    ChannelTarget,
    OutboundContent,
)
from magi_plugin_sdk.delivery import DeliveryChunk, DeliveryContent, DeliveryReceipt

from ..runtime_trace import RuntimeTraceStore
from ..runtime_trace.notification_payloads import (
    AGENT_RESPONSE,
    AGENT_RESPONSE_CHUNK,
    agent_response_chunk_payload,
    agent_response_payload,
    build_notification_record,
)


# Callable signature: (session_id, payload) -> external_message_id
EmitToChat = Callable[[str, dict[str, Any]], Awaitable[str]]


async def _default_emit(session_id: str, payload: dict[str, Any]) -> str:
    """Default emitter used when none is injected. Logs and returns
    a synthetic id — production wires a real emitter via __init__."""
    from ..core.logger import get_logger
    from ..utils.diagnostic_logging import full_content_logging_enabled

    logger = get_logger(__name__)
    if full_content_logging_enabled():
        logger.info(
            "ChatSseChannel default emit (no emitter wired): session=%s payload=%s",
            session_id,
            payload,
        )
    else:
        logger.info(
            "ChatSseChannel default emit (no emitter wired): session=%s payload_fields=%s",
            session_id,
            sorted(str(key) for key in payload),
        )
    return f"synthetic_{int(time.time() * 1000)}"


class ChatSseChannel(Channel):
    """Host-internal Channel for chat SSE delivery.

    ``channel_type`` is now just the scheme (``"chat_sse"``); the
    magi-side session is read from ``target.magi_session_id`` and the
    magi-side user from ``target.magi_user_id``. The session_id routes
    to the correct SSE stream.

    When ``trace_store`` is provided, ``deliver``/``deliver_chunk`` write
    ``RuntimeNotificationRecord`` rows to it on the ``agent_response`` /
    ``agent_response_chunk`` channels, which the chat UI polls.

    When ``trace_store`` is ``None``, falls back to the legacy
    ``emit_to_chat`` callable.

    Chunk-record schema decision: ONE record per ``deliver_chunk`` call,
    with ``payload.is_final`` carrying the boundary. ``payload.event`` is the
    full ``LLMStreamEvent.to_wire_dict`` (falling back to a ``text_delta`` shape
    when the chunk carries no event). The finish boundary is
    conveyed solely by ``is_final=True`` on the payload — no separate
    ``finish`` record. This keeps the record count == chunk count, which
    simplifies cursor/consumer logic and matches the existing wire format
    that NotificationRelay already understands (``payload.is_final``).
    """

    supports_streaming = True
    supports_attachments = True
    supports_revision = False  # SSE renders are immutable in current UI
    inbound_clear_strategy = ChannelInboundClearStrategy.INTERNAL

    CHANNEL_TYPE = "chat_sse"

    def __init__(
        self,
        *,
        trace_store: RuntimeTraceStore | None = None,
        emit_to_chat: EmitToChat | None = None,
    ) -> None:
        self._trace_store = trace_store
        # Preserve existing behavior: when no explicit emit_to_chat is passed,
        # the legacy code path falls back to _default_emit so callers that only
        # use send_message/deliver (and have no trace_store) keep working.
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
        session_id = target.magi_session_id
        await self._emit(session_id, {"text": content.text})

    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        # Phase G: no-op. Frontend already shows typing indicator from streaming chunks.
        return None

    async def deliver(
        self,
        target: ChannelTarget,
        content: DeliveryContent,
    ) -> DeliveryReceipt:
        """Phase G delivery returning a DeliveryReceipt.

        When ``trace_store`` is wired, appends an ``agent_response``
        ``RuntimeNotificationRecord`` and returns a receipt with
        ``external_message_id=None`` (chat SSE has no per-message id).
        Otherwise falls back to the legacy ``emit_to_chat`` path which
        returns a synthetic id.
        """
        session_id = target.magi_session_id
        if self._trace_store is not None:
            # Phase G+1 convergence: carry the richer agent_response fields when
            # supplied (omitted when None → zero change for legacy callers).
            extra_fields = {
                key: getattr(content, key)
                for key in (
                    "turn_id",
                    "message_id",
                    "message_kind",
                    "persona_id",
                    "trace_summary",
                    "ux_plan",
                    "message_payload",
                )
            }
            if content.trace_available:
                extra_fields["trace_available"] = True
            await self._trace_store.append_notification(
                build_notification_record(
                    channel=AGENT_RESPONSE,
                    user_id=str(target.magi_user_id or ""),
                    session_id=session_id,
                    payload=agent_response_payload(
                        user_id=str(target.magi_user_id or ""),
                        session_id=session_id,
                        content=content.text,
                        attachments=[dict(a) for a in content.attachments]
                        if content.attachments
                        else None,
                        extra_fields=extra_fields,
                    ),
                    created_at_ms=int(time.time() * 1000),
                )
            )
            return DeliveryReceipt(
                channel_id=target.channel_type,
                external_message_id=None,
                delivered_at_ms=int(time.time() * 1000),
                magi_session_id=session_id,
            )

        # Legacy fallback
        legacy_payload: dict[str, Any] = {
            "text": content.text,
            "formatting": content.formatting,
        }
        if content.attachments:
            legacy_payload["attachments"] = [dict(a) for a in content.attachments]
        external_id = await self._emit(session_id, legacy_payload)
        return DeliveryReceipt(
            channel_id=target.channel_type,
            external_message_id=external_id,
            delivered_at_ms=int(time.time() * 1000),
            magi_session_id=session_id,
        )

    async def deliver_chunk(
        self,
        target: ChannelTarget,
        chunk: DeliveryChunk,
    ) -> None:
        """Stream one delivery fragment.

        When ``trace_store`` is wired, appends an ``agent_response_chunk``
        ``RuntimeNotificationRecord`` whose payload carries the full
        ``event`` wire-dict (or the legacy ``{"kind": "text_delta", "text":
        chunk.text}`` fallback when the chunk has no event), with the streaming
        boundary carried by ``payload.is_final = chunk.is_final``.

        When no trace_store but an emit callable is set, falls back to a
        synthesized ``_emit(session_id, {"text", "is_final"})`` call so
        legacy wiring continues to receive chunks.
        """
        session_id = target.magi_session_id
        # Phase G+1 fix: take turn_id from the chunk itself when the handler
        # supplies it. Frontend filters chunks
        # by turn_id — empty string was silently dropped, causing the chat
        # UI to look one-shot even though backend emitted 100+ chunks.
        turn_id = str(chunk.turn_id or "")
        if self._trace_store is not None:
            await self._trace_store.append_notification(
                build_notification_record(
                    channel=AGENT_RESPONSE_CHUNK,
                    user_id=str(target.magi_user_id or ""),
                    session_id=session_id,
                    turn_id=turn_id,
                    payload=agent_response_chunk_payload(
                        user_id=str(target.magi_user_id or ""),
                        session_id=session_id,
                        turn_id=turn_id,
                        event=chunk.event
                        if chunk.event is not None
                        else {"kind": "text_delta", "text": chunk.text},
                        is_final=bool(chunk.is_final),
                        seq=int(chunk.seq),
                        persona_id=chunk.persona_id,
                    ),
                    created_at_ms=int(time.time() * 1000),
                )
            )
            return None

        # Legacy fallback: synthesize a chunk-shaped payload through the
        # existing emit_to_chat callable. Note _emit is always set (either
        # injected or _default_emit), so we never silently drop.
        await self._emit(
            session_id,
            {"text": chunk.text, "is_final": bool(chunk.is_final), "seq": int(chunk.seq)},
        )
        return None

    # revise/retract intentionally not overridden — defaults raise NotImplementedError
    # because the chat UI today doesn't model message edits / deletes. Phase F+
    # ConversationLog event-sourcing will make these meaningful.


__all__ = ["ChatSseChannel", "EmitToChat"]
