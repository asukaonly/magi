"""Phase G delivery types: ``DeliveryReceipt`` and ``DeliveryContent``.

These belong on the SDK boundary because plugins authoring channel
adapters (Telegram, Weixin, future Slack/email) need to return / accept
them. ``DeliveryReceipt`` lets the host later call ``revise`` or
``retract`` against a specific delivered message.

Phase I will extend ``DeliveryContent`` with multi-modal
``ContentBlock`` support; Phase G stays text + attachments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """Identifier returned by ``Channel.deliver`` so the host can later
    target the same message for ``revise``/``retract``.

    ``external_message_id`` is the channel's native message identifier
    (Telegram ``message_id``, Slack ``ts``, etc.). ``None`` for
    fire-and-forget channels (webhooks, push notifications) where no
    handle is available for later operations.

    ``magi_session_id`` carries the magi-side session this delivery was
    targeted at. Required for retract-by-session lookups in channels
    (like ``chat_sse``) where ``channel_id`` is just the scheme and
    multiple sessions' receipts would otherwise collide. Defaults to
    ``""`` for channels that don't need session-scoped retract (external
    channels like Telegram identify the message via
    ``external_message_id`` alone).
    """

    channel_id: str
    external_message_id: str | None
    delivered_at_ms: int
    magi_session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "external_message_id": self.external_message_id,
            "delivered_at_ms": int(self.delivered_at_ms),
            "magi_session_id": self.magi_session_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeliveryReceipt":
        return cls(
            channel_id=str(payload["channel_id"]),
            external_message_id=payload.get("external_message_id"),
            delivered_at_ms=int(payload.get("delivered_at_ms") or 0),
            magi_session_id=str(payload.get("magi_session_id") or ""),
        )


@dataclass(frozen=True, slots=True)
class DeliveryChunk:
    """One streaming fragment of a delivery.

    ``seq`` is monotonic per (target, run); ``is_final=True`` marks the
    last chunk for this delivery. ``text`` may be empty on the final
    chunk if the channel only needs the boundary signal.

    ``turn_id`` lets streaming-capable channels (chat_sse) tag each
    chunk with the chat-side turn identifier so consumers can group
    chunks into the right active streaming bubble. Default ``None`` for
    backward compat — channels that don't need it (e.g., non-streaming
    Telegram) simply ignore it.
    """

    text: str
    is_final: bool
    seq: int
    turn_id: str | None = None
    # Phase G+1 convergence: a full stream-event dict (tool_call / reasoning /
    # status / text_flush / text_delta ...) so streaming channels can carry
    # every stream-event kind, not just text_delta. ``None`` → the channel
    # falls back to the legacy ``{"kind": "text_delta", "text": text}`` shape.
    event: dict[str, Any] | None = None
    persona_id: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryContent:
    """Phase G payload: text + attachments + formatting hint.

    Phase I will replace this with a multi-modal ``list[ContentBlock]``;
    Phase G keeps the shape narrow so existing ``Channel.send_message``
    implementations can map ``DeliveryContent → OutboundContent`` with
    no information loss.
    """

    text: str
    attachments: tuple[dict[str, Any], ...] = ()
    formatting: Literal["markdown", "plaintext", "blocks", "html"] = "markdown"
    # Phase G+1 convergence fields. Default ``None`` → channels that don't
    # supply them omit them from the wire payload (zero behavior change). These
    # let ChatSseChannel carry the full ``agent_response`` payload that
    # ChatRuntimeNotifier.emit_agent_response used to own.
    turn_id: str | None = None
    message_id: str | None = None
    message_kind: str | None = None
    persona_id: str | None = None
    trace_summary: dict[str, Any] | None = None
    trace_available: bool = False
    ux_plan: dict[str, Any] | None = None
    message_payload: dict[str, Any] | None = None
    orchestration_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "attachments": [dict(a) for a in self.attachments],
            "formatting": self.formatting,
            "turn_id": self.turn_id,
            "message_id": self.message_id,
            "message_kind": self.message_kind,
            "persona_id": self.persona_id,
            "trace_summary": self.trace_summary,
            "trace_available": self.trace_available,
            "ux_plan": self.ux_plan,
            "message_payload": self.message_payload,
            "orchestration_id": self.orchestration_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeliveryContent":
        return cls(
            text=str(payload.get("text") or ""),
            attachments=tuple(dict(a) for a in (payload.get("attachments") or ())),
            formatting=payload.get("formatting") or "markdown",
            turn_id=payload.get("turn_id"),
            message_id=payload.get("message_id"),
            message_kind=payload.get("message_kind"),
            persona_id=payload.get("persona_id"),
            trace_summary=payload.get("trace_summary"),
            trace_available=bool(payload.get("trace_available")),
            ux_plan=payload.get("ux_plan"),
            message_payload=payload.get("message_payload"),
            orchestration_id=payload.get("orchestration_id"),
        )


__all__ = ["DeliveryReceipt", "DeliveryContent", "DeliveryChunk"]
