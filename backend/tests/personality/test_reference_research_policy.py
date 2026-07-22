from __future__ import annotations

import pytest

from magi.personality.reference_research import (
    ReferenceResearchPolicyInput,
    decide_reference_research,
)


@pytest.mark.parametrize("source_kind", ["original", "private_person_reference"])
def test_research_policy_never_searches_non_public_inputs(source_kind: str) -> None:
    decision = decide_reference_research(
        ReferenceResearchPolicyInput(
            source_kind=source_kind,
            fidelity_level="faithful",
            research_preference="required",
            identity_ambiguous=True,
        )
    )

    assert decision.level == "none"
    assert decision.requires_network is False


def test_research_policy_requires_sources_for_faithful_reference() -> None:
    decision = decide_reference_research(
        ReferenceResearchPolicyInput(
            source_kind="fictional_reference",
            fidelity_level="faithful",
        )
    )

    assert decision.level == "full"
    assert decision.requires_network is True
    assert decision.identity_verification_required is True


def test_research_policy_blocks_faithful_when_network_is_disabled() -> None:
    decision = decide_reference_research(
        ReferenceResearchPolicyInput(
            source_kind="public_person_reference",
            fidelity_level="faithful",
            research_preference="disabled",
        )
    )

    assert decision.blocked_reason == "faithful_requires_research"
    assert decision.requires_network is False


@pytest.mark.parametrize("source_kind", ["fictional_reference", "public_person_reference"])
def test_research_policy_uses_same_ambiguity_rule_for_all_public_references(source_kind: str) -> None:
    decision = decide_reference_research(
        ReferenceResearchPolicyInput(
            source_kind=source_kind,
            fidelity_level="traits",
            identity_ambiguous=True,
            identity_confidence=0.45,
        )
    )

    assert decision.level == "identity"
    assert decision.identity_verification_required is True


def test_research_policy_uses_representative_research_for_low_coverage() -> None:
    decision = decide_reference_research(
        ReferenceResearchPolicyInput(
            source_kind="fictional_reference",
            fidelity_level="natural",
            profile_coverage=0.4,
            volatility="stable",
        )
    )

    assert decision.level == "representative"
    assert "profile_coverage_low" in decision.reason_codes


def test_research_policy_grounds_natural_fidelity_even_with_a_complete_stable_prior() -> None:
    decision = decide_reference_research(
        ReferenceResearchPolicyInput(
            source_kind="fictional_reference",
            fidelity_level="natural",
            profile_coverage=0.9,
            volatility="stable",
            identity_confidence=0.95,
        )
    )

    assert decision.level == "representative"
    assert decision.requires_network is True
    assert "natural_fidelity_requested" in decision.reason_codes


def test_research_policy_can_skip_traits_when_identity_and_prior_are_sufficient() -> None:
    decision = decide_reference_research(
        ReferenceResearchPolicyInput(
            source_kind="fictional_reference",
            fidelity_level="traits",
            profile_coverage=0.9,
            volatility="stable",
            identity_confidence=0.95,
        )
    )

    assert decision.level == "none"
    assert decision.requires_network is False
