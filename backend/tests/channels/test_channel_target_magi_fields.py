from magi_plugin_sdk.channels import ChannelTarget


def test_channel_target_carries_magi_session_and_user_ids():
    t = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s-abc",
        magi_user_id="u-xyz",
    )
    assert t.channel_type == "chat_sse"
    assert t.magi_session_id == "s-abc"
    assert t.magi_user_id == "u-xyz"


def test_channel_target_magi_fields_default_to_empty_string():
    """Backward compat: callers that don't supply magi-side fields should
    still construct successfully (Telegram/Weixin-style channels that
    use external_chat_id for the external system's id)."""
    t = ChannelTarget(channel_type="telegram", external_chat_id="42")
    assert t.magi_session_id == ""
    assert t.magi_user_id == ""


def test_channel_target_positional_args_still_work():
    """external_thread_id was previously the 3rd positional; legacy
    callers passing it positionally must continue to work."""
    t = ChannelTarget("telegram", "42", "thread-123")
    assert t.channel_type == "telegram"
    assert t.external_chat_id == "42"
    assert t.external_thread_id == "thread-123"
    assert t.magi_session_id == ""
    assert t.magi_user_id == ""
