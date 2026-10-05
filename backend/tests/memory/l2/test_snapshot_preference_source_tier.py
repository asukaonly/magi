"""Snapshot preference items must carry a `source_tier` field.

`_add_assertion_preferences` is called by `_build_snapshot_state` with assertion
dicts that include `source_domain` and `user_feedback` (confirmed in
`storage/rows.py::_assertion_row_to_dict`).  The field drives UI phrasing:
  - "authoritative" → "you said…"
  - "inferred"      → "I noticed you…"
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

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


@pytest.mark.parametrize(
    ("source", "feedback", "tier"),
    [
        ("external_activity", None, "inferred"),
        ("user_authored", None, "authoritative"),
        ("external_activity", "confirmed", "authoritative"),
    ],
)
def test_snapshot_preferences_preserve_value_strength_and_source_authority(source, feedback, tier):
    preferences = {}
    _MinimalHost()._add_assertion_preferences(
        preferences=preferences,
        assertions=[_make_assertion(source_domain=source, user_feedback=feedback)],
    )
    assert preferences == {
        "music_genre": {
            "value": "indie",
            "affinity": 0.96,
            "family": "preference_profile",
            "source_tier": tier,
        }
    }


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
