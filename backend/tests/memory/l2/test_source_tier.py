
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


@pytest.mark.parametrize(
    "case_expected_tier,case_source,case_feedback",
    [
        pytest.param(
            "authoritative", "settings_profile", None, id="settings_profile_is_authoritative"
        ),
        pytest.param(
            "authoritative",
            "external_activity",
            "confirmed",
            id="confirmed_feedback_promotes_any_source_to_authoritative",
        ),
        pytest.param(
            "inferred", "external_activity", "rejected", id="rejected_feedback_does_not_promote"
        ),
    ],
)
def test_source_and_feedback_determine_authority_tier(
    case_expected_tier, case_source, case_feedback
):
    assert source_tier(source_domain=case_source, user_feedback=case_feedback) == case_expected_tier


def test_unknown_source_defaults_to_inferred():
    assert source_tier(source_domain="", user_feedback=None) == "inferred"
    assert source_tier(source_domain="runtime_telemetry", user_feedback=None) == "inferred"
