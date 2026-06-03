"""Control-plane request/response dataclasses for plugin channels.

Phase H+2: external-channel control fanout. The host fans out
permission-approval prompts (and future control requests like
confirmations, parameter pickers, etc.) to every channel that opted
into the originating run, not just the desktop SSE channel.

A ``ControlRequest`` is what the host sends OUT to a channel; the
plugin renders it however the platform supports (Telegram inline
buttons, WeChat text instructions, etc.). The plugin's response is
not modeled as a return value here — the user's reply (button tap,
slash command, free-text response) flows back through the normal
inbound message path and the host's slash-command parser correlates
it via ``short_id``.

Why the indirection: channels like WeChat have no synchronous
"prompt" primitive — the only way for the user to respond is by
sending another message. Modeling the response as a return value
would force every adapter to fake a long-lived awaitable, which is
fragile across reconnects and survives across host restarts only by
duplicating the broker's pending-request state per plugin. Keeping
the response path identical to "normal inbound message → slash
command parser → broker.resolve" reuses the existing machinery and
naturally tolerates restarts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ControlRequest:
    """A control-plane prompt the host wants the user to act on.

    Currently the only ``kind`` is ``"permission"`` (tool-approval
    request); future kinds may include ``"confirmation"`` or
    ``"input"`` without breaking the SDK contract.

    Fields:
        request_id: Full ULID of the underlying interaction. Used by
            the broker to resolve(). Channels typically embed this
            (or its short form) in callback data / message metadata
            so the inbound response can route back.
        short_id: Human-typeable correlation token (6-char base32
            lowercased, derived from request_id). Used in
            ``/approve {short_id}`` slash commands so the user
            doesn't have to type a 26-char ULID. Collision-resistant
            within the small pending-request window per session.
        kind: ``"permission"`` for tool-approval; reserved for
            future kinds.
        tool_name: Display name of the tool needing approval
            (e.g. ``"image_gen"``). Surfaced verbatim to the user.
        preview: One-line plain-text summary of what the tool will
            do (e.g. ``'Generate image: "a cat with a hat"'``).
            Plugins MAY truncate for platform-specific limits
            (Telegram callback_data, WeChat 2000-byte text caps).
        risk_level: ``"low" | "medium" | "high"``. Plugins MAY use
            this to vary the rendering (e.g. red warning emoji for
            high-risk). Host decides the value; plugins do not
            interpret it for routing.
        expires_at_ms: Unix milliseconds when the broker will time
            out. Plugins MAY surface a countdown or auto-dismiss
            stale prompts. ``None`` means "no announced deadline".
        payload: Channel-opaque extra context (kill-list reason,
            tool parameters preview, etc.). Plugins MAY ignore.
    """

    request_id: str
    short_id: str
    kind: str
    tool_name: str
    preview: str
    risk_level: str = "medium"
    expires_at_ms: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("ControlRequest.request_id must be non-empty")
        if not self.short_id:
            raise ValueError("ControlRequest.short_id must be non-empty")
        if not self.kind:
            raise ValueError("ControlRequest.kind must be non-empty")
        if not self.tool_name:
            raise ValueError("ControlRequest.tool_name must be non-empty")
        # preview MAY be empty (some tools have no humanly-summarizable
        # preview); risk_level / expires_at_ms / payload MAY be defaults.


__all__ = ["ControlRequest"]
