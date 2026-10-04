def test_host_turn_input_reexports_sdk():
    # Host path must resolve to the SAME class object (so isinstance checks
    # stay consistent across host and plugin code).
    from magi.agent.turn_input import UserTurnInput as host_cls
    from magi_plugin_sdk.turn import UserTurnInput as sdk_cls

    assert host_cls is sdk_cls
