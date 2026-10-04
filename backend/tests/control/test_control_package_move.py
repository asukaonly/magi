def test_cancel_shim_reexports_same_objects():
    # Coupling A: cancel.py moved to magi.control.cancel; the agent.cancel
    # shim must re-export the SAME objects (identity) so agent/* consumers
    # keep working unchanged.
    from magi.agent.cancel import CancelToken as H
    from magi.control.cancel import CancelToken as S
    assert H is S
    import magi.agent.cancel as old_c
    import magi.control.cancel as new_c
    assert old_c.NullCancelToken is new_c.NullCancelToken
    assert old_c.null_cancel_token is new_c.null_cancel_token
    assert old_c.EventCancelToken is new_c.EventCancelToken
    assert old_c.SessionRunCancelToken is new_c.SessionRunCancelToken


def test_bash_grading_shim_reexports_same_sdk_objects():
    # Coupling B: command-risk classifier promoted to the SDK; the
    # _bash_grading shim must re-export the SAME objects (identity) so the
    # L8 tools keep working unchanged.
    from magi.tools.builtin._bash_grading import classify_for_permission as H
    from magi_plugin_sdk.command_risk import classify_for_permission as S
    assert H is S
    import magi.tools.builtin._bash_grading as old_g
    import magi_plugin_sdk.command_risk as new_g
    assert old_g.classify_command is new_g.classify_command
    assert old_g.CommandGrade is new_g.CommandGrade
    assert old_g.RiskLevel is new_g.RiskLevel
