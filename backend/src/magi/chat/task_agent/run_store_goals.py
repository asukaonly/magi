"""Goal projection helpers for chat session runs."""

from __future__ import annotations

from typing import Any

from magi.agent.task_agents.handlers.run_contracts import ActiveRun


class SessionRunGoalMixin:
    """Mirror active chat runs into L0 goal records."""

    _l0_store: Any

    @staticmethod
    def _goal_id(*, run_id: str, revision: int) -> str:
        return f"chat_run:{run_id}:{int(revision)}"

    def _push_root_goal(
        self,
        *,
        session_id: str,
        run_id: str,
        revision: int,
        root_turn_id: str | None,
        root_user_message: str,
    ) -> None:
        description = str(root_user_message or "").strip()
        if not description:
            return
        self._l0_store.push_goal_sync(
            session_id=session_id,
            goal_id=self._goal_id(run_id=run_id, revision=revision),
            goal_type="chat_run",
            description=description,
            status="in_progress",
            priority=0,
            metadata={
                "run_id": run_id,
                "revision": int(revision),
                "root_turn_id": str(root_turn_id or "").strip() or None,
            },
        )

    def _cancel_root_goal(
        self,
        *,
        session_id: str,
        active_run: ActiveRun,
        reason: str,
    ) -> None:
        self._l0_store.set_goal_status_sync(
            session_id=session_id,
            goal_id=self._goal_id(run_id=active_run.run_id, revision=active_run.revision),
            status="cancelled",
            result_summary=reason,
        )

    def _complete_root_goal(
        self,
        *,
        session_id: str,
        active_run: ActiveRun,
    ) -> None:
        self._l0_store.set_goal_status_sync(
            session_id=session_id,
            goal_id=self._goal_id(run_id=active_run.run_id, revision=active_run.revision),
            status="completed",
            result_summary="Chat run completed",
        )


__all__ = ["SessionRunGoalMixin"]
