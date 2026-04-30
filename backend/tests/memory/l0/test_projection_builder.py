from __future__ import annotations

from magi.memory.l0.contracts import L0ExecutionSummary, L0PromptWorkbenchProjection
from magi.memory.l0.working.projection import build_execution_summary


def test_build_execution_summary_marks_current_pending_turns_as_replan() -> None:
    summary = build_execution_summary(
        run={
            "status": "running",
            "revision": 2,
            "root_user_message": "Investigate the login issue",
        },
        pending_turns=[
            {
                "turn_id": "turn-2",
                "content": "补充一下，是 macOS",
                "revision": 2,
            }
        ],
    )

    assert summary == L0ExecutionSummary(
        active_run_summary="Investigate the login issue",
        awaiting_external_result=False,
        waiting_reason="user_replan_pending",
        latest_user_augmentation_summary="补充一下，是 macOS",
    )


def test_build_execution_summary_marks_running_without_pending_turns_as_external_wait() -> None:
    summary = build_execution_summary(
        run={
            "status": "running",
            "revision": 2,
            "root_user_message": "Investigate the login issue",
        },
        pending_turns=[],
    )

    assert summary == L0ExecutionSummary(
        active_run_summary="Investigate the login issue",
        awaiting_external_result=True,
        waiting_reason="external_result",
        latest_user_augmentation_summary=None,
    )


def test_build_execution_summary_ignores_pending_turns_from_older_revisions() -> None:
    summary = build_execution_summary(
        run={
            "status": "running",
            "revision": 3,
            "root_user_message": "Investigate the login issue",
        },
        pending_turns=[
            {
                "turn_id": "turn-2",
                "content": "补充一下，是 macOS",
                "revision": 2,
            }
        ],
    )

    assert summary == L0ExecutionSummary(
        active_run_summary="Investigate the login issue",
        awaiting_external_result=True,
        waiting_reason="external_result",
        latest_user_augmentation_summary=None,
    )


def test_build_execution_summary_marks_current_results_as_checkpoint_ready() -> None:
    summary = build_execution_summary(
        run={
            "status": "running",
            "revision": 3,
            "root_user_message": "Investigate the login issue",
        },
        pending_turns=[],
        accepted_results=[
            {
                "result_id": "result-1",
                "revision": 3,
                "payload": {"content": "tool result"},
            }
        ],
    )

    assert summary == L0ExecutionSummary(
        active_run_summary="Investigate the login issue",
        awaiting_external_result=False,
        waiting_reason="checkpoint_ready",
        latest_user_augmentation_summary=None,
    )


def test_prompt_projection_emits_retrieval_entry_shape() -> None:
    projection = L0PromptWorkbenchProjection(
        session={"id": "s1"},
        goal_stack=["g1", "g2", "g3", "g4"],
        active_entities=["e1", "e2", "e3", "e4", "e5", "e6"],
        temporary_tactics=["t1", "t2", "t3", "t4", "t5", "t6"],
        execution_summary=L0ExecutionSummary(
            active_run_summary="Investigate the login issue",
            awaiting_external_result=False,
            latest_user_augmentation_summary="补充一下，是 macOS",
        ),
    )

    assert projection.to_retrieval_entry() == {
        "session": {"id": "s1"},
        "goals": ["g1", "g2", "g3", "g4"],
        "active_entities": ["e1", "e2", "e3", "e4", "e5", "e6"],
        "temporary_tactics": ["t1", "t2", "t3", "t4", "t5", "t6"],
        "execution_summary": {
            "active_run_summary": "Investigate the login issue",
            "awaiting_external_result": False,
            "waiting_reason": None,
            "latest_user_augmentation_summary": "补充一下，是 macOS",
        },
    }
