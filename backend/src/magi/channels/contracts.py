"""Typed contracts for the channel abstraction layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ChannelTarget:
    """Identifies an external conversation endpoint."""

    channel_type: str
    external_chat_id: str
    external_thread_id: str | None = None


@dataclass(slots=True)
class InboundMessage:
    """Normalized message from any external platform."""

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
    """Normalized response to send to an external platform."""

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
