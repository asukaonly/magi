"""Tests for the 'interest' branch of _apply_assertion_scope."""

from __future__ import annotations

from magi.memory.l2.candidate_models import L2AssertionCandidate
from magi.memory.l2.pipeline.validation.assertions import L2AssertionValidationMixin


def _candidate(trait_family: str) -> L2AssertionCandidate:
    """Build a minimal L2AssertionCandidate with only trait_family specified."""
    return L2AssertionCandidate(
        entity_ref="user:test",
        entity_type="user",
        trait_family=trait_family,
        trait_name="test_trait",
        trait_value="some_value",
    )


class _MinimalHost(L2AssertionValidationMixin):
    """Minimal concrete subclass for testing _apply_assertion_scope directly."""

    pass


def test_interest_scope_keeps_preference_taste_and_topology_families():
    host = _MinimalHost()
    candidates = [
        _candidate("preference_profile"),
        _candidate("taste_profile"),
        _candidate("group_atmosphere"),
        _candidate("mood"),  # excluded — not in interest set
    ]

    result = host._apply_assertion_scope(
        raw_candidates=candidates,
        assertion_scope="interest",
    )

    result_families = {c.trait_family for c in result}
    assert result_families == {"preference_profile", "taste_profile", "group_atmosphere"}


def test_interest_scope_keeps_all_topology_families():
    host = _MinimalHost()
    candidates = [
        _candidate("public_sentiment"),
        _candidate("relationship_shift"),
        _candidate("group_atmosphere"),
        _candidate("stress"),  # excluded
    ]

    result = host._apply_assertion_scope(
        raw_candidates=candidates,
        assertion_scope="interest",
    )

    result_families = {c.trait_family for c in result}
    assert result_families == {"public_sentiment", "relationship_shift", "group_atmosphere"}


def test_interest_scope_excludes_mood_and_stress():
    host = _MinimalHost()
    candidates = [
        _candidate("mood"),
        _candidate("stress"),
        _candidate("engagement"),
        _candidate("preference_profile"),
    ]

    result = host._apply_assertion_scope(
        raw_candidates=candidates,
        assertion_scope="interest",
    )

    result_families = {c.trait_family for c in result}
    assert result_families == {"preference_profile"}
    assert "mood" not in result_families
    assert "stress" not in result_families
    assert "engagement" not in result_families
