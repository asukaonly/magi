"""Channel authoring contracts for Magi plugins."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .delivery import DeliveryChunk, DeliveryContent, DeliveryReceipt


@dataclass(slots=True)
class ChannelTarget:
    """Identify an external conversation endpoint."""

    channel_type: str
    external_chat_id: str
    external_thread_id: str | None = None


@dataclass(slots=True)
class InboundMessage:
    """Normalize a message received from any external platform."""

    channel_type: str
    external_chat_id: str
    external_user_id: str
    external_message_id: str
    external_username: str | None = None
    text: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)
    is_group: bool = False
    is_mention: bool = False
    reply_to_external_id: str | None = None
    thread_id: str | None = None
    raw_event: Any = None


@dataclass(slots=True)
class OutboundContent:
    """Normalize response content sent to an external platform."""

    text: str
    is_final: bool = True
    is_streaming_chunk: bool = False
    reply_to_external_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChannelSessionMapping:
    """Persisted link between an external chat and a Magi session."""

    channel_type: str
    external_chat_id: str
    magi_session_id: str
    magi_user_id: str
    is_group: bool = False
    created_at_ms: int = 0
    last_active_at_ms: int = 0
    metadata_json: str = "{}"


@dataclass(slots=True)
class ChannelConfig:
    """Base channel configuration contract."""

    enabled: bool = False
    magi_user_id: str = "default"
    allowed_user_ids: list[str] = field(default_factory=list)
    group_trigger_keyword: str = ""


@dataclass(slots=True)
class ChannelMessageDispatchOutcome:
    """Result returned by the host when a channel dispatches an inbound message."""

    success: bool
    user_id: str
    session_id: str | None = None
    turn_id: str | None = None
    message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    queue_size: int | None = None


@runtime_checkable
class ChannelAttachmentStoreProtocol(Protocol):
    """Host-provided storage facade for channel-owned inbound attachments."""

    async def store_attachment(
        self,
        *,
        session_id: str,
        turn_id: str,
        kind: str,
        original_name: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        """Persist one attachment and return a chat attachment payload."""


@runtime_checkable
class ChannelSessionMapperProtocol(Protocol):
    """Host-provided session mapping facade injected into channels."""

    async def resolve_or_create(
        self,
        *,
        channel_type: str,
        external_chat_id: str,
        external_user_id: str,
        is_group: bool = False,
        display_name: str | None = None,
    ) -> ChannelSessionMapping:
        """Resolve or create the Magi session mapping for an external chat."""

    async def lookup(
        self,
        channel_type: str,
        external_chat_id: str,
    ) -> ChannelSessionMapping | None:
        """Look up an existing mapping by external chat identity."""

    async def lookup_by_session(
        self,
        magi_session_id: str,
    ) -> ChannelSessionMapping | None:
        """Look up an existing mapping by Magi session identifier."""

    async def delete_mapping(
        self,
        channel_type: str,
        external_chat_id: str,
    ) -> None:
        """Delete a channel session mapping."""

    async def get_notification_cursor(
        self,
        channel_type: str,
        external_chat_id: str,
    ) -> int:
        """Return the last delivered notification cursor for a channel chat."""

    async def update_notification_cursor(
        self,
        channel_type: str,
        external_chat_id: str,
        notification_id: int,
    ) -> None:
        """Persist the last delivered notification cursor for a channel chat."""


@runtime_checkable
class ChannelMessageDispatcherProtocol(Protocol):
    """Host-provided inbound message dispatch facade injected into channels."""

    async def dispatch_user_message(
        self,
        *,
        source: str,
        user_id: str,
        message: str,
        session_id: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        reply_to_message_id: str | None = None,
        workspace_path: str | None = None,
        client_turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        runtime_namespace: str | None = None,
    ) -> ChannelMessageDispatchOutcome:
        """Dispatch one inbound channel message into the Magi runtime."""


class Channel(ABC):
    """A bidirectional messaging channel connected to an external platform.

    Phase G additions:
    - Capability flags (class attributes): ``supports_streaming``,
      ``supports_revision``, ``supports_attachments``.
    - ``deliver(target, content)`` — modern delivery returning a
      ``DeliveryReceipt``. Defaults to wrapping ``send_message`` so
      existing implementations keep working.
    - ``revise(receipt, new_content)`` — edit an already-delivered
      message. Defaults to ``NotImplementedError`` so the host knows
      to fall back to "send correction" semantics.
    - ``retract(receipt)`` — delete an already-delivered message.
      Defaults to ``NotImplementedError`` for the same reason.
    """

    # === Phase G capability flags (override in subclass) ===
    supports_streaming: bool = False
    supports_revision: bool = False
    supports_attachments: bool = True  # most channels support text + attachments

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Return the unique channel type identifier."""

    @abstractmethod
    async def start(self) -> None:
        """Initialize the platform connection."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the platform connection."""

    @abstractmethod
    async def send_message(self, target: ChannelTarget, content: OutboundContent) -> None:
        """Deliver a message to an external chat via the platform API."""

    @abstractmethod
    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        """Show typing or processing state on the external platform."""

    async def deliver(
        self,
        target: "ChannelTarget",
        content: "DeliveryContent",
    ) -> "DeliveryReceipt":
        """Phase G delivery. Default: wrap legacy ``send_message``.

        Subclasses that want the receipt's ``external_message_id`` to
        carry a real channel-native ID (Telegram message_id, Slack ts)
        should override this method directly.
        """
        from .delivery import DeliveryReceipt

        legacy_content = OutboundContent(text=content.text)
        await self.send_message(target, legacy_content)
        return DeliveryReceipt(
            channel_id=target.channel_type,
            external_message_id=None,  # legacy channels have no native id
            delivered_at_ms=int(time.time() * 1000),
        )

    async def deliver_chunk(
        self,
        target: "ChannelTarget",
        chunk: "DeliveryChunk",
    ) -> None:
        """Stream one fragment of a delivery.

        Channels that opt into streaming via ``supports_streaming = True``
        must override. Non-streaming channels see only the assembled content
        via ``deliver()``; this default raises so silent drops cannot happen.
        """
        raise NotImplementedError(
            f"Channel {type(self).__name__!s} did not implement deliver_chunk; "
            "either set supports_streaming = False or override deliver_chunk."
        )

    async def revise(
        self,
        receipt: "DeliveryReceipt",
        new_content: "DeliveryContent",
    ) -> "DeliveryReceipt":
        """Phase G edit. Default: NotImplementedError.

        Channels that support editing (Telegram via editMessageText,
        Slack via chat.update) should override.
        """
        raise NotImplementedError(
            f"Channel {type(self).__name__} does not support revise; "
            f"override Channel.revise() and set supports_revision=True"
        )

    async def retract(
        self,
        receipt: "DeliveryReceipt",
    ) -> None:
        """Phase G retract. Default: NotImplementedError.

        Channels that support deletion (Telegram deleteMessage, Slack
        chat.delete) should override. Channels that can't (email)
        should keep the default and rely on the host sending a
        ``(message retracted)`` correction message.
        """
        raise NotImplementedError(
            f"Channel {type(self).__name__} does not support retract; "
            f"override Channel.retract() if the channel supports it"
        )

    def bind_session_mapper(self, session_mapper: ChannelSessionMapperProtocol) -> None:
        """Inject the host-provided session mapper after construction."""
        _ = session_mapper

    def bind_message_dispatcher(self, dispatcher: ChannelMessageDispatcherProtocol) -> None:
        """Inject the host-provided inbound message dispatcher after construction."""
        _ = dispatcher

    def bind_attachment_store(self, attachment_store: ChannelAttachmentStoreProtocol) -> None:
        """Inject the host-provided attachment store after construction."""
        _ = attachment_store


__all__ = [
    "Channel",
    "ChannelConfig",
    "ChannelAttachmentStoreProtocol",
    "ChannelMessageDispatcherProtocol",
    "ChannelMessageDispatchOutcome",
    "ChannelSessionMapperProtocol",
    "ChannelSessionMapping",
    "ChannelTarget",
    "InboundMessage",
    "OutboundContent",
]