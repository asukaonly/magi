"""Permission fanout target resolution — CF-3 of the control fanout work.

Pins the contract that:
* Every fanout always includes chat_sse (so desktop can approve).
* Non-empty, non-chat_sse origin_channel is appended (so the
  channel-the-user-is-chatting-from gets the prompt too).
* chat_sse-as-origin is a no-op (no duplicate target).
* Unbound (session_id=None) requests return empty (orphan — only
  the global runtime_notifications path reaches desktop).
"""
from __future__ import annotations

from magi.control.permission.fanout import resolve_permission_fanout_targets


def test_no_origin_returns_chat_sse_only() -> None:
    """No external channel triggered this run → desktop SSE only."""
    targets = resolve_permission_fanout_targets(
        session_id="sess-1", user_id="local_user", origin_channel=None,
    )
    assert [t.channel_type for t in targets] == ["chat_sse"]
    assert targets[0].magi_session_id == "sess-1"
    assert targets[0].magi_user_id == "local_user"
    assert targets[0].external_chat_id == ""


def test_weixin_origin_appends_after_chat_sse() -> None:
    """WeChat-triggered run → fanout to BOTH desktop SSE AND WeChat."""
    targets = resolve_permission_fanout_targets(
        session_id="sess-1", user_id="local_user", origin_channel="weixin",
    )
    assert [t.channel_type for t in targets] == ["chat_sse", "weixin"]
    assert targets[1].magi_session_id == "sess-1"
    assert targets[1].magi_user_id == "local_user"
    assert targets[1].external_chat_id == ""  # plugin resolves at deliver-time


def test_telegram_origin_appends_after_chat_sse() -> None:
    """Same pattern for Telegram — the resolver doesn't special-case
    scheme names, treats any non-empty non-chat_sse value as a target."""
    targets = resolve_permission_fanout_targets(
        session_id="sess-1", user_id="local_user", origin_channel="telegram",
    )
    assert [t.channel_type for t in targets] == ["chat_sse", "telegram"]


def test_chat_sse_origin_is_noop() -> None:
    """When the desktop itself originated the run, no duplicate
    chat_sse target — single chat_sse target is correct."""
    targets = resolve_permission_fanout_targets(
        session_id="sess-1", user_id="local_user", origin_channel="chat_sse",
    )
    assert [t.channel_type for t in targets] == ["chat_sse"]


def test_blank_origin_is_normalized_to_chat_sse_only() -> None:
    """Whitespace / empty origin defensively normalized to no-origin
    semantics — never produce an empty channel_type target."""
    for blank in ("", "   ", None):
        targets = resolve_permission_fanout_targets(
            session_id="sess-1", user_id="local_user", origin_channel=blank,
        )
        assert [t.channel_type for t in targets] == ["chat_sse"]


def test_orphan_request_no_session_id_returns_empty() -> None:
    """No session → no fanout possible. Desktop still gets the
    prompt via runtime_notifications (global queue), so this
    isn't a regression — just no per-channel fanout for orphan
    requests."""
    targets = resolve_permission_fanout_targets(
        session_id=None, user_id="local_user", origin_channel="weixin",
    )
    assert targets == []
