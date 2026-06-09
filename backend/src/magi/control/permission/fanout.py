"""Permission fanout target resolution — Phase H+2.

Builds the ``ChannelTarget`` list used by
``DeliveryRouter.fanout_control_request`` (CF-4) to send a permission
approval prompt to every place the user might realistically respond.

The contract is intentionally narrower than the reply fanout
(``magi.channels.delivery_prefs.resolve_delivery_targets``). Reply
fanout walks ``user_prefs.delivery_channels`` so a single answer can
echo to every linked surface (desktop SSE + WeChat + Telegram +
future Slack). Permission fanout deliberately does NOT do that:

* Spamming every linked channel with an approval prompt every time a
  tool needs gating would be a UX disaster (push notifications on
  three devices for every image-gen).
* The legitimately reachable surfaces are exactly two: the channel
  the user is currently chatting from (so they see the prompt where
  they're already attentive) and the desktop SSE (always polled, so
  the user can switch to desktop if they want a better UI).

That's why this module exists separately from ``delivery_prefs.py``.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from magi_plugin_sdk.channels import ChannelTarget

#: Async lookup ``session_id -> originating channel scheme``.
#:
#: Production implementation (wired in CF-5 / bootstrap) reads
#: ``AgentRun.trigger.source_channel`` from the
#: ``SessionRunRegistry`` for the session's currently-active run.
#: Returns ``None`` when there's no active run, no trigger, or no
#: ``source_channel`` set — fanout then falls back to chat_sse-only.
OriginChannelResolver = Callable[[str], Awaitable[str | None]]


def resolve_permission_fanout_targets(
    *,
    session_id: str | None,
    user_id: str,
    origin_channel: str | None,
) -> list[ChannelTarget]:
    """Compute the ``ChannelTarget`` list for a permission approval fanout.

    Always includes ``chat_sse`` (so the desktop user can approve
    via the existing modal regardless of which channel triggered the
    run). Conditionally appends ``origin_channel`` when it's a
    non-empty, non-``chat_sse`` scheme — duplicate suppression in
    the simplest possible way.

    ``session_id == None`` is an orphan request (no chat session
    bound). Returns an empty list — the prompter still writes to
    ``runtime_notifications`` (the desktop's global queue), so the
    desktop sees the prompt; we just can't fanout to any external
    channel because nobody knows where to send it.

    ``magi_user_id`` is stamped onto every returned target so
    downstream plugins can resolve the external chat_id from
    ``ChannelSessionMapper`` at deliver time (same pattern as the
    reply fanout).
    """
    if not session_id:
        return []

    targets: list[ChannelTarget] = [_chat_sse_target(session_id, user_id)]

    normalized_origin = (origin_channel or "").strip()
    if normalized_origin and normalized_origin != "chat_sse":
        targets.append(
            ChannelTarget(
                channel_type=normalized_origin,
                external_chat_id="",
                magi_session_id=session_id,
                magi_user_id=user_id,
            )
        )
    return targets


def _chat_sse_target(session_id: str, user_id: str) -> ChannelTarget:
    return ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id=session_id,
        magi_user_id=user_id,
    )


__all__ = ["OriginChannelResolver", "resolve_permission_fanout_targets"]
