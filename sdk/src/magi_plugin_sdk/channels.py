"""Channel authoring contracts for Magi plugins."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .control import ControlRequest
    from .delivery import DeliveryChunk, DeliveryContent, DeliveryReceipt


@dataclass(slots=True)
class ChannelTarget:
    """Identify a destination for a delivery.

    ``channel_type`` is the registry SCHEME only (e.g. "chat_sse",
    "telegram"). DeliveryRouter looks up channels by exactly this string.

    ``external_chat_id`` / ``external_thread_id`` carry the external
    platform's identifiers (Telegram chat_id, Slack channel/thread, etc.)
    when the channel maps to an external system. Empty when the channel
    is magi-native (e.g. chat_sse).

    ``magi_session_id`` / ``magi_user_id`` carry magi-side context so
    magi-native channels can route, and external channels can perform
    their own session->external-id lookups (via session_mapper, etc.).
    """

    channel_type: str
    external_chat_id: str
    external_thread_id: str | None = None
    magi_session_id: str = ""
    magi_user_id: str = ""


@dataclass(slots=True)
class InboundMessage:
    """Normalize a message received from any external platform."""

    channel_type: str
    external_chat_id: str
    external_user_id: str
    external_message_id: str
    provider_occurred_at_ms: int
    external_username: str | None = None
    text: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)
    is_group: bool = False
    is_mention: bool = False
    reply_to_external_id: str | None = None
    thread_id: str | None = None
    raw_event: Any = None


class ChannelInboundRejectionReason(str, Enum):
    """Stable terminal reasons for rejecting an external inbound message."""

    INVALID_METADATA = "invalid_metadata"
    CLEARED_MESSAGE = "cleared_message"


class ChannelInboundRejectedError(RuntimeError):
    """Raised when an external inbound message must be dropped permanently.

    Channel plugins must treat this error as a terminal delivery result: advance
    the provider cursor or acknowledge the update, and do not retry it. Retrying
    cannot make an event from before a destructive clear admissible again.
    """

    def __init__(
        self,
        reason: ChannelInboundRejectionReason,
        message: str,
    ) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ChannelInboundContext:
    """Host-issued admission context for one external provider event.

    A plugin must obtain this context before creating a session mapping,
    persisting attachments, handling a control command, or dispatching a chat
    message. The same context must be passed to every host call for that event.
    """

    provider_occurred_at_ms: int
    clear_generation: int


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


@dataclass(slots=True)
class ChannelControlCommandResult:
    """Outcome of a host control command (permission / session / help).

    Returned by :meth:`ChannelControlPortProtocol.handle_command` when the inbound
    message WAS a control command. ``None`` (not this type) means "not a command —
    dispatch as normal chat". ``ack`` is the short text the channel surfaces to the
    user; ``kind`` names the command family ("permission" / "session" / "help") for
    plugin-side routing or logging.
    """

    ack: str | None = None
    kind: str = ""


@runtime_checkable
class ChannelAttachmentStoreProtocol(Protocol):
    """Host-provided storage facade for channel-owned inbound attachments."""

    async def store_attachment(
        self,
        *,
        inbound_context: ChannelInboundContext,
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
        inbound_context: ChannelInboundContext,
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

    async def capture_inbound_context(
        self,
        *,
        provider_occurred_at_ms: int,
    ) -> ChannelInboundContext:
        """Admit a provider event before any host-owned state is created.

        ``provider_occurred_at_ms`` must be the provider's event timestamp, not
        the local polling or receipt time. A rejected event is terminal and must
        not be retried.
        """

    async def dispatch_user_message(
        self,
        *,
        inbound_context: ChannelInboundContext,
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


@runtime_checkable
class ChannelControlPortProtocol(Protocol):
    """Host-provided control-command facade injected into channels.

    Owns ALL channel control commands in one place — permission (``/approve|/deny``),
    session (``/new|/reset``), ``/help`` — so the command set and the session-mapping
    reset chain live host-side, not duplicated per plugin. A channel calls
    ``handle_command`` for an inbound message BEFORE dispatching it as chat: a
    non-``None`` result means it was a control command (surface ``result.ack`` and
    stop); ``None`` means dispatch via :class:`ChannelMessageDispatcherProtocol`.
    """

    async def handle_command(
        self,
        *,
        inbound_context: ChannelInboundContext,
        message: str,
        session_id: str | None,
        channel_type: str,
        external_chat_id: str,
        external_user_id: str,
    ) -> "ChannelControlCommandResult | None":
        """Handle ``message`` if it is a control command, else return ``None``."""


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

    # === Phase H+2 control-plane capability flag (override in subclass) ===
    # ``True`` if the channel implements ``deliver_control_request`` —
    # used by the host's DeliveryRouter.fanout_control_request to skip
    # channels that haven't opted in, instead of catching
    # NotImplementedError per call. Plugins that override the method
    # MUST also flip this flag.
    supports_control_requests: bool = False

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

    async def deliver_control_request(
        self,
        target: "ChannelTarget",
        request: "ControlRequest",
    ) -> None:
        """Phase H+2 control-plane fanout. Default: NotImplementedError.

        When a tool call hits the permission gate, the host fans out
        a ControlRequest to every channel connected to the
        originating user (desktop SSE + the channel the user is
        actually chatting from). Channels that opt in (Telegram with
        inline buttons, WeChat with text instructions) override this
        method and set ``supports_control_requests = True``.

        The plugin's only contract here is "render the prompt in
        whatever the platform supports." The user's response flows
        back through the normal inbound message path — either a
        button-tap-callback synthesized into ``/approve {short_id}``
        (Telegram) or the user typing ``/approve {short_id}``
        verbatim (WeChat). The host's slash-command parser correlates
        the response back to ``request.request_id`` via short_id.

        Channels that can't render any kind of out-of-band prompt
        (pure email, batch-only platforms) should keep the default;
        the host will silently skip them.
        """
        raise NotImplementedError(
            f"Channel {type(self).__name__} does not support control "
            f"requests; override Channel.deliver_control_request() "
            f"and set supports_control_requests=True if the channel "
            f"can render approval prompts."
        )

    def bind_session_mapper(self, session_mapper: ChannelSessionMapperProtocol) -> None:
        """Inject the host-provided session mapper after construction."""
        _ = session_mapper

    def bind_message_dispatcher(self, dispatcher: ChannelMessageDispatcherProtocol) -> None:
        """Inject the host-provided inbound message dispatcher after construction.

        The channel must call ``capture_inbound_context`` before any other
        host-owned inbound operation and pass the returned context through the
        entire ingress flow.
        """
        _ = dispatcher

    def bind_attachment_store(self, attachment_store: ChannelAttachmentStoreProtocol) -> None:
        """Inject the host-provided attachment store after construction."""
        _ = attachment_store

    def bind_control_port(self, control_port: "ChannelControlPortProtocol") -> None:
        """Inject the host-provided control-command port after construction."""
        _ = control_port


__all__ = [
    "Channel",
    "ChannelConfig",
    "ChannelInboundContext",
    "ChannelInboundRejectedError",
    "ChannelInboundRejectionReason",
    "ChannelAttachmentStoreProtocol",
    "ChannelControlCommandResult",
    "ChannelControlPortProtocol",
    "ChannelMessageDispatcherProtocol",
    "ChannelMessageDispatchOutcome",
    "ChannelSessionMapperProtocol",
    "ChannelSessionMapping",
    "ChannelTarget",
    "InboundMessage",
    "OutboundContent",
]
