
import pytest
from magi.memory.l2.assertions.source_tier import source_tier


@pytest.mark.parametrize(
    "expected_tier,source_kind",
    [
        pytest.param("authoritative", "user_authored", id="user_authored_is_authoritative"),
        pytest.param("inferred", "external_activity", id="external_activity_is_inferred"),
    ],
)
def test_source_tier_reflects_authorship(expected_tier, source_kind):
    assert source_tier(source_domain=source_kind, user_feedback=None) == expected_tier


def test_settings_profile_is_authoritative():
    assert source_tier(source_domain="settings_profile", user_feedback=None) == "authoritative"


def test_confirmed_feedback_promotes_any_source_to_authoritative():
    assert source_tier(source_domain="external_activity", user_feedback="confirmed") == "authoritative"


def test_rejected_feedback_does_not_promote():
    assert source_tier(source_domain="external_activity", user_feedback="rejected") == "inferred"


def test_unknown_source_defaults_to_inferred():
    assert source_tier(source_domain="", user_feedback=None) == "inferred"
    assert source_tier(source_domain="runtime_telemetry", user_feedback=None) == "inferred"
