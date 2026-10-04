"""Tests for L3 reflection write contracts."""

from __future__ import annotations


from magi.memory.l3.models import L3Candidate


class TestL3Candidate:
    def test_defaults_task_reflection_to_insight(self) -> None:
        candidate = L3Candidate(
            content="The user clarified that growth matters more than salary.",
            source_event_ids=["evt-1", "evt-2"],
            summary_category="task_reflection",
        )

        assert candidate.summary_type == "insight"
        assert candidate.subtypes == []
