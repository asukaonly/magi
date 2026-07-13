"""Tests for portrait admission and horizon boundaries."""

from __future__ import annotations

import pytest

from magi.user_profile.portrait_signal_policy import classify_assertion_portrait


@pytest.mark.parametrize(
    ("assertion", "expected_role", "expected_group"),
    [
        (
            {
                "trait_family": "interest_profile",
                "trait_name": "interest.diiv",
                "validation_state": "stable",
                "temporal_scope": "recent",
            },
            "recent",
            None,
        ),
        (
            {
                "trait_family": "interest_profile",
                "trait_name": "interest.diiv",
                "validation_state": "stable",
                "temporal_scope": "stable",
            },
            "world",
            "preferences",
        ),
        (
            {
                "trait_family": "project_profile",
                "trait_name": "project.magi",
                "validation_state": "corroborated",
                "temporal_scope": "stable",
            },
            "world",
            "projects",
        ),
        (
            {
                "trait_family": "routine_profile",
                "trait_name": "routine.tool.codex",
                "validation_state": "stable",
                "temporal_scope": "stable",
            },
            "skip",
            None,
        ),
        (
            {
                "trait_family": "project_profile",
                "trait_name": "project.magi",
                "validation_state": "tentative",
                "temporal_scope": "stable",
            },
            "review",
            None,
        ),
    ],
)
def test_portrait_role_follows_assertion_horizon(
    assertion: dict[str, str],
    expected_role: str,
    expected_group: str | None,
) -> None:
    decision = classify_assertion_portrait(assertion)

    assert decision.role == expected_role
    assert decision.world_group == expected_group


def test_portrait_does_not_guess_missing_horizon() -> None:
    decision = classify_assertion_portrait(
        {
            "trait_family": "interest_profile",
            "trait_name": "interest.diiv",
            "validation_state": "stable",
        }
    )

    assert decision.role == "skip"
