"""Snapshot preference items must carry a `source_tier` field.

`_add_assertion_preferences` is called by `_build_snapshot_state` with assertion
dicts that include `source_domain` and `user_feedback` (confirmed in
`storage/rows.py::_assertion_row_to_dict`).  The field drives UI phrasing:
  - "authoritative" → "you said…"
  - "inferred"      → "I noticed you…"
"""

from __future__ import annotations

from typing import Any, Dict

from magi.memory.l2.assertions.snapshot_assembly import L2SnapshotAssemblyMixin


def _make_assertion(
    *,
    trait_family: str = "preference_profile",
    trait_name: str = "music_genre",
    trait_value: str = "indie",
    confidence_score: float = 0.8,
    evidence_events: list[str] | None = None,
    source_domain: str | None = "external_activity",
    user_feedback: str | None = None,
    validation_state: str = "stable",
) -> Dict[str, Any]:
    return {
        "assertion_id": "a1",
        "trait_family": trait_family,
        "trait_name": trait_name,
        "trait_value": trait_value,
        "confidence_score": confidence_score,
        "evidence_events": evidence_events if evidence_events is not None else ["e1", "e2"],
        "source_domain": source_domain,
        "user_feedback": user_feedback,
        "validation_state": validation_state,
    }


class _MinimalHost(L2SnapshotAssemblyMixin):
    """Minimal concrete host so we can call the mixin method directly."""


def test_inferred_source_domain_gives_inferred_source_tier():
    """external_activity + no feedback → inferred."""
    host = _MinimalHost()
    preferences: Dict[str, Any] = {}
    assertion = _make_assertion(source_domain="external_activity", user_feedback=None)
    host._add_assertion_preferences(preferences=preferences, assertions=[assertion])

    assert "music_genre" in preferences
    assert preferences["music_genre"]["value"] == "indie"
    assert preferences["music_genre"]["source_tier"] == "inferred"


def test_user_authored_source_domain_gives_authoritative_source_tier():
    """user_authored → authoritative."""
    host = _MinimalHost()
    preferences: Dict[str, Any] = {}
    assertion = _make_assertion(source_domain="user_authored", user_feedback=None)
    host._add_assertion_preferences(preferences=preferences, assertions=[assertion])

    assert "music_genre" in preferences
    assert preferences["music_genre"]["source_tier"] == "authoritative"


def test_confirmed_feedback_promotes_to_authoritative():
    """user_feedback='confirmed' on any source_domain → authoritative."""
    host = _MinimalHost()
    preferences: Dict[str, Any] = {}
    assertion = _make_assertion(source_domain="external_activity", user_feedback="confirmed")
    host._add_assertion_preferences(preferences=preferences, assertions=[assertion])

    assert preferences["music_genre"]["source_tier"] == "authoritative"


def test_preference_profile_family_also_tagged():
    """preference_profile family assertions also get source_tier."""
    host = _MinimalHost()
    preferences: Dict[str, Any] = {}
    assertion = _make_assertion(
        trait_family="preference_profile",
        trait_name="music_genre",
        source_domain="external_activity",
        user_feedback=None,
    )
    host._add_assertion_preferences(preferences=preferences, assertions=[assertion])

    assert "music_genre" in preferences
    assert preferences["music_genre"]["source_tier"] == "inferred"


def test_affinity_and_family_fields_still_present():
    """Existing fields (value, affinity, family) are not removed."""
    host = _MinimalHost()
    preferences: Dict[str, Any] = {}
    assertion = _make_assertion(confidence_score=0.8, evidence_events=["e1", "e2"])
    host._add_assertion_preferences(preferences=preferences, assertions=[assertion])

    pref = preferences["music_genre"]
    assert "value" in pref
    assert "affinity" in pref
    assert "family" in pref
    assert "source_tier" in pref  # new field present


def test_non_pref_families_not_included():
    """Assertions with a non-preference family are still excluded."""
    host = _MinimalHost()
    preferences: Dict[str, Any] = {}
    assertion = _make_assertion(trait_family="mood_state", trait_name="mood")
    host._add_assertion_preferences(preferences=preferences, assertions=[assertion])

    assert "mood" not in preferences


def test_preference_dot_prefix_still_skipped():
    """Assertions with trait_name starting with 'preference.' still skipped (legacy path)."""
    host = _MinimalHost()
    preferences: Dict[str, Any] = {}
    assertion = _make_assertion(trait_name="preference.color", trait_family="preference_profile")
    host._add_assertion_preferences(preferences=preferences, assertions=[assertion])

    assert "preference.color" not in preferences
