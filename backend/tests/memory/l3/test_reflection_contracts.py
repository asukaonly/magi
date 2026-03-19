"""Tests for L3 reflection write contracts."""

from __future__ import annotations

from dataclasses import asdict

from magi.memory.l3.models import L3Candidate, TaskOutcomePacket


class TestTaskOutcomePacket:
    def test_keeps_user_goal_and_evidence(self) -> None:
        packet = TaskOutcomePacket(
            task_id="task-1",
            user_id="u1",
            task_title="Plan job switch",
            task_status="completed",
            user_goal="Decide whether to start applying this month",
            evidence_event_ids=["evt-1", "evt-2"],
        )

        data = asdict(packet)

        assert data["user_goal"] == "Decide whether to start applying this month"
        assert data["evidence_event_ids"] == ["evt-1", "evt-2"]


class TestL3Candidate:
    def test_defaults_task_reflection_to_insight(self) -> None:
        candidate = L3Candidate(
            content="The user clarified that growth matters more than salary.",
            source_event_ids=["evt-1", "evt-2"],
            summary_category="task_reflection",
        )

        assert candidate.summary_type == "insight"
        assert candidate.subtypes == []
