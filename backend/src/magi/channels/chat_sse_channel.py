"""ChatSseChannel — wraps the chat UI's runtime_trace notification bus as
a first-class ``Channel`` so the same ``DeliveryRouter`` handles SSE
delivery alongside Telegram/Weixin/future channels.

Phase G+1: the chat UI's SSE bus is the ``runtime_trace_store`` notification
table — chat frontends poll it for ``agent_response`` (final assembled reply)
and ``agent_response_chunk`` (streaming text deltas) records. When a
``trace_store`` is wired into this channel, ``deliver``/``deliver_chunk``
append rows directly there, mirroring the schema produced by
``ChatRuntimeNotifier.emit_agent_response`` / ``emit_stream_event`` in
``magi.chat.task_agent.postprocess.notifications``.

Backward compat: the legacy ``emit_to_chat`` callable still works when
``trace_store=None``. Both may be set independently.

Phase I will deepen with multi-modal ContentBlock streaming.
"""

from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable

from magi_plugin_sdk.channels import Channel, ChannelTarget, OutboundContent
from magi_plugin_sdk.delivery import DeliveryChunk, DeliveryContent, DeliveryReceipt

from ..runtime_trace import RuntimeNotificationRecord, RuntimeTraceStore


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
    with ``payload.is_final`` carrying the boundary. The ``event.kind`` is
    always ``text_delta`` (matching ``ChatRuntimeNotifier.emit_stream_event``
    which wraps an ``LLMStreamEvent.to_wire_dict``). The finish boundary is
    conveyed solely by ``is_final=True`` on the payload — no separate
    ``finish`` record. This keeps the record count == chunk count, which
    simplifies cursor/consumer logic and matches the existing wire format
    that NotificationRelay already understands (``payload.is_final``).
    """

    supports_streaming = True
    supports_attachments = True
    supports_revision = False  # SSE renders are immutable in current UI

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
            payload: dict[str, Any] = {
                "user_id": target.magi_user_id,
                "session_id": session_id,
                "content": content.text,
                "is_final": True,
                "timestamp": time.time(),
            }
            if content.attachments:
                payload["attachments"] = [dict(a) for a in content.attachments]
            await self._trace_store.append_notification(
                RuntimeNotificationRecord(
                    notification_id=0,
                    channel="agent_response",
                    user_id=str(target.magi_user_id or ""),
                    session_id=session_id,
                    payload_json=json.dumps(payload, ensure_ascii=False),
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
        ``RuntimeNotificationRecord`` whose payload mirrors
        ``ChatRuntimeNotifier.emit_stream_event``: ``event = {"kind":
        "text_delta", "text": chunk.text}``, with the streaming boundary
        carried by ``payload.is_final = chunk.is_final``.

        When no trace_store but an emit callable is set, falls back to a
        synthesized ``_emit(session_id, {"text", "is_final"})`` call so
        legacy wiring continues to receive chunks.
        """
        session_id = target.magi_session_id
        # Phase G+1 fix: take turn_id from the chunk itself when the handler
        # supplies it (DirectLLMHandler now does). Frontend filters chunks
        # by turn_id — empty string was silently dropped, causing the chat
        # UI to look one-shot even though backend emitted 100+ chunks.
        turn_id = str(chunk.turn_id or "")
        if self._trace_store is not None:
            payload: dict[str, Any] = {
                "user_id": target.magi_user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "event": {"kind": "text_delta", "text": chunk.text},
                "is_final": bool(chunk.is_final),
                "seq": int(chunk.seq),
                "timestamp": time.time(),
            }
            await self._trace_store.append_notification(
                RuntimeNotificationRecord(
                    notification_id=0,
                    channel="agent_response_chunk",
                    user_id=str(target.magi_user_id or ""),
                    session_id=session_id,
                    turn_id=turn_id,
                    payload_json=json.dumps(payload, ensure_ascii=False),
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
