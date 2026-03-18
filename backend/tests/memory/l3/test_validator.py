"""Tests for L3 reflection validation and routing."""

from __future__ import annotations

from magi.memory.l3.models import L3Candidate, TaskOutcomePacket
from magi.memory.l3.validator import validate_candidate


class TestValidateCandidate:
    def test_rejects_missing_evidence(self) -> None:
        candidate = L3Candidate(
            summary_type="insight",
            summary_category="task_reflection",
            content="The user clarified the main decision criteria.",
            source_event_ids=[],
        )

        decision = validate_candidate(candidate, evidence_events=[])

        assert decision.action == "reject"
        assert decision.reason == "missing_evidence"

    def test_routes_execution_trace_like_task_outcomes_to_l4(self) -> None:
        packet = TaskOutcomePacket(
            task_id="task-1",
            user_id="u1",
            task_title="Run repo explore",
            task_status="completed",
            result_summary="Called rg, retried twice, then worker finished.",
            evidence_event_ids=["evt-1", "evt-2"],
        )
        candidate = L3Candidate(
            summary_type="insight",
            summary_category="task_reflection",
            content="The task called rg, retried twice, and completed successfully.",
            source_event_ids=["evt-1", "evt-2"],
        )

        decision = validate_candidate(
            candidate,
            task_outcome=packet,
            evidence_events=[
                {"event_id": "evt-1", "memory_domain": "runtime_telemetry", "retention_class": "compressible"},
                {"event_id": "evt-2", "memory_domain": "runtime_telemetry", "retention_class": "compressible"},
            ],
        )

        assert decision.action == "route_to_l4"
        assert decision.reason == "execution_trace"

    def test_accepts_user_facing_task_reflection(self) -> None:
        packet = TaskOutcomePacket(
            task_id="task-2",
            user_id="u1",
            task_title="Plan job switch",
            task_status="completed",
            user_goal="Decide whether to start applying this month",
            result_summary="Clarified priorities and next steps for a job switch.",
            evidence_event_ids=["evt-1", "evt-2"],
            decisions=[{"content": "Growth matters more than salary."}],
            next_steps=["Finish the portfolio homepage."],
        )
        candidate = L3Candidate(
            summary_type="insight",
            summary_category="task_reflection",
            content="The user clarified that growth matters more than salary and should finish the portfolio homepage before applying.",
            source_event_ids=["evt-1", "evt-2"],
        )

        decision = validate_candidate(
            candidate,
            task_outcome=packet,
            evidence_events=[
                {"event_id": "evt-1", "memory_domain": "user_authored", "retention_class": "permanent"},
                {"event_id": "evt-2", "memory_domain": "interaction", "retention_class": "compressible"},
            ],
        )

        assert decision.action == "accept"
        assert decision.reason == "accepted"
