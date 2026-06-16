from magi.memory.l2.assertions.source_tier import source_tier


def test_user_authored_is_authoritative():
    assert source_tier(source_domain="user_authored", user_feedback=None) == "authoritative"


def test_settings_profile_is_authoritative():
    assert source_tier(source_domain="settings_profile", user_feedback=None) == "authoritative"


def test_external_activity_is_inferred():
    assert source_tier(source_domain="external_activity", user_feedback=None) == "inferred"


def test_confirmed_feedback_promotes_any_source_to_authoritative():
    assert source_tier(source_domain="external_activity", user_feedback="confirmed") == "authoritative"


def test_rejected_feedback_does_not_promote():
    assert source_tier(source_domain="external_activity", user_feedback="rejected") == "inferred"


def test_unknown_source_defaults_to_inferred():
    assert source_tier(source_domain="", user_feedback=None) == "inferred"
    assert source_tier(source_domain="runtime_telemetry", user_feedback=None) == "inferred"
