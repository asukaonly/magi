"""Tests for assertion trait-family classification."""

from __future__ import annotations

import pytest

from magi.memory.l2.assertions.reconcile_state import L2ReconcileStateMixin


@pytest.mark.parametrize(
    ("trait_name", "expected_family"),
    [
        ("interest.diiv", "interest_profile"),
        ("project.magi", "project_profile"),
        ("routine.late_night_coding", "routine_profile"),
        ("preference.music", "preference_profile"),
    ],
)
def test_derive_trait_family_keeps_profile_semantics(
    trait_name: str,
    expected_family: str,
) -> None:
    state = L2ReconcileStateMixin()

    assert state._derive_trait_family(trait_name) == expected_family


def test_interest_traits_are_recommended_for_preference_snapshot() -> None:
    state = L2ReconcileStateMixin()

    assert (
        state._recommend_snapshot_field(
            trait_name="interest.diiv",
            status="stable",
        )
        == "preferences"
    )
