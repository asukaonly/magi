"""Explicit destination routing and immutable target snapshots."""
from dataclasses import FrozenInstanceError
import pytest
from magi.delivery.routing import build_delivery_plan
from magi_plugin_sdk.endpoints import EndpointRef


def test_same_channel_accounts_and_threads_are_distinct_targets():
    origin = EndpointRef("account-a", "telegram", "chat", "topic-1")
    other_thread = EndpointRef("account-a", "telegram", "chat", "topic-2")
    other_account = EndpointRef("account-b", "telegram", "chat", "topic-1")
    preferences = {"delivery_targets": [origin.to_dict(), other_thread.to_dict(), other_account.to_dict()]}
    plan = build_delivery_plan(session_id="s", user_id="u", reply_to=origin, user_prefs=preferences)
    assert plan.targets == (EndpointRef(None, "chat_sse", "s"), origin, other_thread, other_account)
    targets = plan.channel_targets()
    assert [(t.channel_type, t.external_chat_id, t.external_thread_id) for t in targets[1:]] == [
        ("account-a:telegram", "chat", "topic-1"), ("account-a:telegram", "chat", "topic-2"),
        ("account-b:telegram", "chat", "topic-1"),
    ]
    preferences["delivery_targets"].clear()
    assert len(plan.targets) == 4
    with pytest.raises(FrozenInstanceError):
        plan.targets = ()


def test_native_origin_updates_conversation_once_without_broadcasting_elsewhere():
    plan = build_delivery_plan(
        session_id="s", user_id="u", reply_to=EndpointRef(None, "chat_sse", "s", device_id="phone"),
    )
    assert plan.targets == (EndpointRef(None, "chat_sse", "s"),)


@pytest.mark.parametrize("targets", ["telegram", ["telegram"], [None], [{"target_id": "chat"}], [{}] * 33])
def test_incomplete_or_unbounded_destinations_are_rejected(targets):
    with pytest.raises((ValueError, TypeError)):
        build_delivery_plan(session_id="s", user_id="u", user_prefs={"delivery_targets": targets})


def test_cannot_redirect_native_conversation_sync_to_another_session():
    target = EndpointRef(None, "chat_sse", "other-session")
    with pytest.raises(ValueError, match="another session"):
        build_delivery_plan(session_id="s", user_id="u", user_prefs={"delivery_targets": [target.to_dict()]})
