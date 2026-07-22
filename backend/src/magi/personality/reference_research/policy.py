"""Deterministic policy for persona reference research depth."""

from __future__ import annotations

from .models import ReferenceResearchDecision, ReferenceResearchPolicyInput

_IDENTITY_CONFIDENCE_THRESHOLD = 0.78
_PROFILE_COVERAGE_THRESHOLD = 0.68


def decide_reference_research(
    policy_input: ReferenceResearchPolicyInput,
) -> ReferenceResearchDecision:
    """Choose research depth without branching on celebrity or character type."""
    if policy_input.source_kind == "original":
        return ReferenceResearchDecision(
            level="none",
            requires_network=False,
            identity_verification_required=False,
            reason_codes=["original_persona"],
        )
    if policy_input.source_kind == "private_person_reference":
        return ReferenceResearchDecision(
            level="none",
            requires_network=False,
            identity_verification_required=False,
            reason_codes=["private_reference"],
        )

    identity_required = any(
        (
            policy_input.identity_ambiguous,
            policy_input.identity_confidence < _IDENTITY_CONFIDENCE_THRESHOLD,
            policy_input.reference_modified,
            policy_input.fidelity_level == "faithful" and not policy_input.identity_verified,
        )
    )
    reasons: list[str] = []
    if policy_input.identity_ambiguous:
        reasons.append("identity_ambiguous")
    if policy_input.identity_confidence < _IDENTITY_CONFIDENCE_THRESHOLD:
        reasons.append("identity_confidence_low")
    if policy_input.reference_modified:
        reasons.append("reference_modified")
    if policy_input.has_user_reference_urls:
        reasons.append("user_reference_urls")

    if policy_input.research_preference == "disabled":
        if policy_input.fidelity_level == "faithful":
            return ReferenceResearchDecision(
                level="none",
                requires_network=False,
                identity_verification_required=identity_required,
                blocked_reason="faithful_requires_research",
                reason_codes=[*reasons, "network_disabled"],
            )
        return ReferenceResearchDecision(
            level="none",
            requires_network=False,
            identity_verification_required=False,
            reason_codes=[*reasons, "network_disabled"],
        )

    if policy_input.fidelity_level == "faithful":
        return ReferenceResearchDecision(
            level="full",
            requires_network=True,
            identity_verification_required=True,
            reason_codes=[*reasons, "faithful_requested"],
        )

    if policy_input.research_preference == "required":
        return ReferenceResearchDecision(
            level="representative",
            requires_network=True,
            identity_verification_required=identity_required,
            reason_codes=[*reasons, "research_required"],
        )

    needs_representative_research = any(
        (
            policy_input.has_user_reference_urls,
            policy_input.fidelity_level == "natural"
            and policy_input.profile_coverage < _PROFILE_COVERAGE_THRESHOLD,
            policy_input.fidelity_level == "natural"
            and policy_input.volatility in {"evolving", "current"},
        )
    )
    if needs_representative_research:
        if policy_input.profile_coverage < _PROFILE_COVERAGE_THRESHOLD:
            reasons.append("profile_coverage_low")
        if policy_input.volatility in {"evolving", "current"}:
            reasons.append(f"reference_{policy_input.volatility}")
        return ReferenceResearchDecision(
            level="representative",
            requires_network=True,
            identity_verification_required=identity_required,
            reason_codes=reasons,
        )

    if identity_required:
        return ReferenceResearchDecision(
            level="identity",
            requires_network=True,
            identity_verification_required=True,
            reason_codes=reasons,
        )

    return ReferenceResearchDecision(
        level="none",
        requires_network=False,
        identity_verification_required=False,
        reason_codes=[*reasons, "model_prior_sufficient_for_requested_depth"],
    )


__all__ = ["decide_reference_research"]
