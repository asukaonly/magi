from __future__ import annotations

from magi.memory.l0.contracts import L0ExecutionSummary
from magi.memory.l0.projection_builder import build_execution_summary


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
        latest_user_augmentation_summary=None,
    )
