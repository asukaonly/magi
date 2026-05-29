"""Phase G delivery types: ``DeliveryReceipt`` and ``DeliveryContent``.

These belong on the SDK boundary because plugins authoring channel
adapters (Telegram, Weixin, future Slack/email) need to return / accept
them. ``DeliveryReceipt`` lets the host later call ``revise`` or
``retract`` against a specific delivered message.

Phase I will extend ``DeliveryContent`` with multi-modal
``ContentBlock`` support; Phase G stays text + attachments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """Identifier returned by ``Channel.deliver`` so the host can later
    target the same message for ``revise``/``retract``.

    ``external_message_id`` is the channel's native message identifier
    (Telegram ``message_id``, Slack ``ts``, etc.). ``None`` for
    fire-and-forget channels (webhooks, push notifications) where no
    handle is available for later operations.
    """

    channel_id: str
    external_message_id: str | None
    delivered_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "external_message_id": self.external_message_id,
            "delivered_at_ms": int(self.delivered_at_ms),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeliveryReceipt":
        return cls(
            channel_id=str(payload["channel_id"]),
            external_message_id=payload.get("external_message_id"),
            delivered_at_ms=int(payload.get("delivered_at_ms") or 0),
        )


@dataclass(frozen=True, slots=True)
class DeliveryChunk:
    """One streaming fragment of a delivery.

    ``seq`` is monotonic per (target, run); ``is_final=True`` marks the
    last chunk for this delivery. ``text`` may be empty on the final
    chunk if the channel only needs the boundary signal.
    """

    text: str
    is_final: bool
    seq: int


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "attachments": [dict(a) for a in self.attachments],
            "formatting": self.formatting,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeliveryContent":
        return cls(
            text=str(payload.get("text") or ""),
            attachments=tuple(dict(a) for a in (payload.get("attachments") or ())),
            formatting=payload.get("formatting") or "markdown",
        )


__all__ = ["DeliveryReceipt", "DeliveryContent", "DeliveryChunk"]
