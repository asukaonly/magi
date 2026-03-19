"""Tests for task-driven L3 reflection candidate building."""

from __future__ import annotations

import pytest

from magi.memory.l3.models import TaskOutcomePacket
from magi.memory.l3.task_reflection_service import TaskReflectionService


@pytest.mark.asyncio
async def test_build_candidate_from_completed_user_goal_task() -> None:
    service = TaskReflectionService()

    candidate = await service.build_candidate(
        TaskOutcomePacket(
            task_id="task-1",
            user_id="u1",
            task_kind="user_goal_task",
            task_title="Plan job switch",
            task_status="completed",
            user_goal="Decide whether to start applying this month",
            result_summary="Clarified priorities and next steps for a job switch.",
            evidence_event_ids=["evt-1", "evt-2"],
            decisions=[{"content": "Growth matters more than salary."}],
            next_steps=["Finish the portfolio homepage."],
        )
    )

    assert candidate is not None
    assert candidate.summary_category == "task_reflection"
    assert candidate.summary_type == "insight"
    assert "growth matters more than salary" in candidate.content.lower()
    assert "Finish the portfolio homepage." in candidate.content
    assert "decision_summary" in candidate.subtypes
    assert "next_step_reflection" in candidate.subtypes


@pytest.mark.asyncio
async def test_build_candidate_returns_none_for_execution_only_task() -> None:
    service = TaskReflectionService()

    candidate = await service.build_candidate(
        TaskOutcomePacket(
            task_id="task-2",
            user_id="u1",
            task_kind="orchestration_task",
            task_title="Run repo explore",
            task_status="completed",
            result_summary="Called rg, retried twice, then worker finished.",
            evidence_event_ids=["evt-1", "evt-2"],
        )
    )

    assert candidate is None
