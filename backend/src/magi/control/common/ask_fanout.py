"""Lightweight ask→channel egress hook.

The ask-user capability (``magi.bootstrap.tool_capabilities._HostInteractionPort.ask``)
surfaces a mid-turn question to the DESKTOP — runtime_notifications quick-reply
chips plus a persisted ``ask_request`` transcript message. It had no built-in
egress to EXTERNAL channels, so a question raised during a WeChat/Telegram-
originated turn never reached the user there: they could neither see nor answer
it, and the turn blocked until timeout.

This module is that missing egress, kept deliberately small:

* a late-bound callback (:func:`bind_ask_fanout_callback` /
  :func:`get_ask_fanout_callback`) that ``ChannelsModule`` wires at startup —
  mirrors the permission prompter's ``bind_fanout_callback``, but lives as a
  module-level hook because the ask flow has no prompter object to hang it on;
* :func:`build_ask_fanout_targets` — pure target resolution (external origin
  channel only; the desktop already has the chips + transcript card);
* :func:`format_ask_for_channel` — pure text formatting (question + numbered
  options + a reply hint);
* :func:`deliver_ask_to_channel` — resolve the session's origin channel and
  deliver, kept here (not as a lifecycle closure) so the lookup → target →
  fanout composition is unit-testable.

Both the producer (bootstrap ask port) and the binder (channels module) import
this lazily from inside functions, so no new top-level cross-layer import edge
is introduced (``bootstrap→control`` / ``channels→control`` stay lint-imports
clean).

The answer round-trip needs no code here: an inbound channel reply already
routes to the pending ask via
``message_dispatch_service._resolve_pending_ask_response`` — it looks up
``ask_state(session_id)`` and resolves the broker BEFORE starting a new turn,
on the channel plugin's own dispatch task, so a foreground ask never deadlocks
behind the blocked turn. (Only a text reply resolves it: an empty message
starts a new turn and attachments are rejected.)
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Optional

from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent

logger = logging.getLogger(__name__)

#: Signature: ``(*, session_id, user_id, request_id, question, options,
#: expires_at_ms) -> Awaitable[None]``. Implemented by ``ChannelsModule``.
AskFanoutCallback = Callable[..., Awaitable[None]]

_ask_fanout_callback: Optional[AskFanoutCallback] = None


def bind_ask_fanout_callback(callback: AskFanoutCallback | None) -> None:
    """Late-bind (or clear, with ``None``) the ask→channel fanout callback.

    Idempotent — overwrites any prior binding. Called by ``ChannelsModule``
    once the channel registry + delivery router exist (it initialises after
    the ask port). Passing ``None`` disables fanout (desktop-only path)."""
    global _ask_fanout_callback
    _ask_fanout_callback = callback


def get_ask_fanout_callback() -> AskFanoutCallback | None:
    """Return the bound ask→channel fanout callback, or ``None`` when no
    external-channel egress is wired (desktop-only deployments / tests)."""
    return _ask_fanout_callback


def reset_ask_fanout_callback() -> None:
    """Test hook — clear the module-level binding between tests."""
    global _ask_fanout_callback
    _ask_fanout_callback = None


def build_ask_fanout_targets(
    *,
    session_id: str | None,
    user_id: str,
    origin_channel: str | None,
) -> list[ChannelTarget]:
    """Compute the ``ChannelTarget`` list for an ask fanout.

    Unlike the permission fanout (which always includes ``chat_sse`` so the
    desktop modal can approve), the ask fanout targets ONLY the external origin
    channel: the desktop already receives the question as quick-reply chips and
    a persisted ``ask_request`` transcript card, so re-delivering it over
    chat_sse would be redundant.

    Returns an empty list — i.e. no external fanout — when there is no session,
    no origin channel, or the origin is ``chat_sse`` (a desktop-only turn).
    ``external_chat_id`` is left blank; the channel plugin resolves it from the
    session mapping at deliver time (same pattern as the reply / permission
    fanout).
    """
    if not session_id:
        return []
    normalized = (origin_channel or "").strip()
    if not normalized or normalized == "chat_sse":
        return []
    return [
        ChannelTarget(
            channel_type=normalized,
            external_chat_id="",
            magi_session_id=session_id,
            magi_user_id=user_id,
        )
    ]


def format_ask_for_channel(
    question: str,
    options: list[str] | None,
    *,
    hint: str = "（直接回复消息作答即可）",
) -> str:
    """Format a mid-turn question for a plain-text channel message.

    Renders the question, then any options as a numbered list, then a one-line
    hint that the user answers by replying with a normal text message (only a
    text reply resolves the ask — an empty message starts a new turn and
    attachments are rejected). ``hint`` is a parameter so the caller can
    localise it later without changing this function.
    """
    lines = [(question or "").strip()]
    opts = [o.strip() for o in (options or []) if o and o.strip()]
    if opts:
        lines.append("")
        lines.extend(f"{i}. {opt}" for i, opt in enumerate(opts, 1))
    if hint:
        lines.append("")
        lines.append(hint)
    return "\n".join(lines).strip()


async def deliver_ask_to_channel(
    *,
    session_id: str,
    user_id: str | None,
    question: str,
    options: list[str],
    session_mapper: Any,
    delivery_router: Any,
    default_user_id: str,
) -> None:
    """Resolve the session's origin channel and deliver the question to it.

    No-op when the session has no external channel mapping (a desktop-only
    session) or the wiring is incomplete. Errors are swallowed — a failed
    fanout must never break the ask (the desktop path is unaffected and the
    turn still waits for an answer that can arrive from the desktop).
    """
    if not session_id or session_mapper is None or delivery_router is None:
        return
    try:
        mapping = await session_mapper.lookup_by_session(session_id)
    except Exception:  # noqa: BLE001 — lookup failure must not break the ask
        logger.debug("ask_fanout.session_lookup_failed", exc_info=True)
        return
    origin_channel = getattr(mapping, "channel_type", None) if mapping else None
    targets = build_ask_fanout_targets(
        session_id=session_id,
        user_id=str(user_id or default_user_id),
        origin_channel=origin_channel,
    )
    if not targets:
        return
    try:
        await delivery_router.fanout_deliver(
            content=DeliveryContent(text=format_ask_for_channel(question, options)),
            targets=targets,
        )
    except Exception:  # noqa: BLE001 — delivery failure must not break the ask
        logger.debug("ask_fanout.deliver_failed", exc_info=True)


__all__ = [
    "AskFanoutCallback",
    "bind_ask_fanout_callback",
    "get_ask_fanout_callback",
    "reset_ask_fanout_callback",
    "build_ask_fanout_targets",
    "format_ask_for_channel",
    "deliver_ask_to_channel",
]
