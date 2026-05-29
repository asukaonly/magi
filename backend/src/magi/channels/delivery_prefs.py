"""Delivery preference resolution — Phase G.

Translates a user's stored delivery channel preferences into a list of
``ChannelTarget``s for ``DeliveryRouter.fanout_deliver``.

Phase G default: chat_sse for the current session only. Users with
external channel preferences (Telegram, Weixin, future Slack/email)
get those appended.

Note on ChannelTarget field usage:
    The SDK's ``ChannelTarget`` uses ``channel_type`` + ``external_chat_id``.
    Phase G uses ``channel_type`` as a composite key (e.g. "chat_sse:s1",
    "telegram:U42") so ``DeliveryRouter`` can look up the correct channel
    instance. ``external_chat_id`` carries the user_id for external
    channels or the session_id for chat_sse.

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
) -> list[ChannelTarget]:
    """Return the list of channels to deliver this run's reply to.

    ``user_prefs.delivery_channels``: list[str] of channel IDs.
    Special values:
      - ``"chat_sse"`` (no session suffix): expanded to ``"chat_sse:<session_id>"``
      - any concrete ``"<scheme>:<id>"``: passed through verbatim as channel_type
      - empty / missing list: defaults to chat_sse-only
    """
    requested = user_prefs.get("delivery_channels") if isinstance(user_prefs, dict) else None
    if not requested or not isinstance(requested, list):
        return [_chat_sse_target(session_id, user_id)]

    targets: list[ChannelTarget] = []
    for channel_id in requested:
        if not isinstance(channel_id, str) or not channel_id.strip():
            continue
        if channel_id == "chat_sse":
            targets.append(_chat_sse_target(session_id, user_id))
        else:
            targets.append(ChannelTarget(channel_type=channel_id, external_chat_id=user_id))
    if not targets:
        # All entries were invalid / filtered — fall back to default.
        return [_chat_sse_target(session_id, user_id)]
    return targets


def _chat_sse_target(session_id: str, user_id: str) -> ChannelTarget:
    return ChannelTarget(channel_type=f"chat_sse:{session_id}", external_chat_id=user_id)


__all__ = ["resolve_delivery_targets"]
