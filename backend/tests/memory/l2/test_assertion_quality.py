"""Quality checks for L2 assertion output."""

from __future__ import annotations

from magi.memory.l2.assertions.quality import analyze_assertion_quality


def test_assertion_quality_flags_internal_source_noise_and_weak_external_profile_items():
    report = analyze_assertion_quality(
        [
            {
                "assertion_id": "assert-noisy-source",
                "trait_family": "preference_profile",
                "trait_name": "interest.codex",
                "trait_value": "Codex",
                "source_domain": "external_activity",
                "validation_state": "stable",
                "evidence_count": 1,
            },
            {
                "assertion_id": "assert-blank",
                "trait_family": "routine_profile",
                "trait_name": "tool.empty",
                "trait_value": "",
                "source_domain": "external_activity",
                "validation_state": "tentative",
                "evidence_count": 3,
            },
            {
                "assertion_id": "assert-good",
                "trait_family": "routine_profile",
                "trait_name": "tool.docker",
                "trait_value": "Docker",
                "source_domain": "external_activity",
                "validation_state": "corroborated",
                "evidence_count": 4,
            },
        ]
    )

    assert report.total_assertions == 3
    assert report.issue_counts == {
        "blank_value": 1,
        "single_evidence_external_profile": 1,
    }
    assert [item.assertion_id for item in report.issue_items] == [
        "assert-noisy-source",
        "assert-blank",
    ]
