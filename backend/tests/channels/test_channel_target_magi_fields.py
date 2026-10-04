from magi_plugin_sdk.channels import ChannelTarget


def test_channel_target_magi_fields_default_to_empty_string():
    """Backward compat: callers that don't supply magi-side fields should
    still construct successfully (Telegram/Weixin-style channels that
    use external_chat_id for the external system's id)."""
    t = ChannelTarget(channel_type="telegram", external_chat_id="42")
    assert t.magi_session_id == ""
    assert t.magi_user_id == ""
