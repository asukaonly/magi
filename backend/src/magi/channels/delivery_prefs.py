"""Delivery preference resolution — Phase G.

Translates a user's stored delivery channel preferences into a list of
``ChannelTarget``s for ``DeliveryRouter.fanout_deliver``.

Phase G default: chat_sse for the current session only. Users with
external channel preferences (Telegram, Weixin, future Slack/email)
get those appended.

Note on ChannelTarget field usage:
    The SDK's ``ChannelTarget`` uses ``channel_type`` as the registry
    SCHEME only (e.g. ``"chat_sse"``, ``"telegram"``). The resulting
    targets carry magi-side context via ``magi_session_id`` /
    ``magi_user_id`` so each Channel can perform its own translation
    to external identifiers at deliver time (e.g. Telegram looks up
    its chat_id via session_mapper). ``external_chat_id`` is left
    empty by this layer — channels populate it themselves.

Future Phase G+1 will plumb user_prefs from the real user-preference
store (currently sourced via ``get_user_preference``).
"""

from __future__ import annotations

from typing import Any

from magi_plugin_sdk.channels import ChannelTarget


def resolve_delivery_targets(
    *,
    user_id: str,
    session_id: str,
    user_prefs: dict[str, Any],
    origin_channel: str | None = None,
) -> list[ChannelTarget]:
    """Return the list of channels to deliver this run's reply to.

    ``user_prefs.delivery_channels``: list[str] of channel SCHEMES
    (e.g. ``["chat_sse", "telegram"]``). The resulting ChannelTargets
    carry magi-side context (session_id, user_id) so each Channel can
    perform its own translation to external identifiers (e.g. Telegram
    looks up its chat_id via session_mapper at deliver time).

    Default (no prefs): chat_sse-only for the current session.

    ``origin_channel``: when non-empty, the channel SCHEME that
    triggered this run (sourced from ``RunTrigger.source_channel`` at
    the coordinator's fanout call site — set to ``"weixin"`` /
    ``"telegram"`` / ``"chat_sse"`` by ``agent/run_triggers.py:build_user_message_trigger``).
    It's appended to the target list unless an equal-scheme target is
    already present, so a reply to an inbound WeChat / Telegram / etc.
    message goes back to that channel even when the user hasn't
    explicitly listed it in ``delivery_channels``. Without this
    auto-append, an inbound from WeChat would only fanout to chat_sse
    and the WeChat user would never hear back. ``chat_sse`` as origin
    is effectively a no-op since the default target list already
    includes it; passing it explicitly is still honored for symmetry.
    """
    requested = user_prefs.get("delivery_channels") if isinstance(user_prefs, dict) else None
    if not requested or not isinstance(requested, list):
        targets: list[ChannelTarget] = [_chat_sse_target(session_id, user_id)]
    else:
        targets = []
        for channel_id in requested:
            if not isinstance(channel_id, str) or not channel_id.strip():
                continue
            if channel_id == "chat_sse":
                targets.append(_chat_sse_target(session_id, user_id))
            else:
                targets.append(ChannelTarget(
                    channel_type=channel_id,
                    external_chat_id="",
                    magi_session_id=session_id,
                    magi_user_id=user_id,
                ))
        if not targets:
            # All entries were invalid / filtered — fall back to default.
            targets = [_chat_sse_target(session_id, user_id)]

    normalized_origin = (origin_channel or "").strip()
    if normalized_origin and not any(t.channel_type == normalized_origin for t in targets):
        if normalized_origin == "chat_sse":
            targets.append(_chat_sse_target(session_id, user_id))
        else:
            targets.append(ChannelTarget(
                channel_type=normalized_origin,
                external_chat_id="",
                magi_session_id=session_id,
                magi_user_id=user_id,
            ))
    return targets


def _chat_sse_target(session_id: str, user_id: str) -> ChannelTarget:
    return ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id=session_id,
        magi_user_id=user_id,
    )


__all__ = ["resolve_delivery_targets"]
