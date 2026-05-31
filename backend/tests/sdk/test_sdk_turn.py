def test_sdk_exposes_user_turn_input():
    from magi_plugin_sdk.turn import UserTurnInput

    t = UserTurnInput(text="hi")
    assert t.text == "hi"
    assert t.attachments == []
    assert t.user_id is None
    assert t.session_id is None


def test_host_turn_input_reexports_sdk():
    # Host path must resolve to the SAME class object (so isinstance checks
    # stay consistent across host and plugin code).
    from magi.agent.turn_input import UserTurnInput as host_cls
    from magi_plugin_sdk.turn import UserTurnInput as sdk_cls

    assert host_cls is sdk_cls
