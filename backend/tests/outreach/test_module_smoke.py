from magi.outreach.lifecycle import OutreachModule


def test_module_declares_expected_dependencies():
    mod = OutreachModule(context=object())
    assert mod.name == "runtime_outreach"
    deps = set(mod.dependencies)
    assert {"runtime_agent_core", "runtime_channels", "runtime_scheduler",
            "runtime_chat_store", "runtime_personality"} <= deps
