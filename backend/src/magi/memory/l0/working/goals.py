"""Goal stack helpers for L0 working memory."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Protocol, cast


class _L0GoalHostProtocol(Protocol):
    _goal_stack: dict[str, list[dict[str, Any]]]

    async def start_session(self, *, session_id: str, **kwargs: Any) -> dict[str, Any]: ...

    def _ensure_session_sync(self, session_id: str) -> dict[str, Any]: ...


class L0GoalStackMixin:
    """Own in-memory L0 goal stack operations."""

    async def push_goal(
        self,
        *,
        session_id: str,
        goal_id: str,
        goal_type: str,
        description: str,
        status: str = "pending",
        priority: int = 0,
        parent_goal_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Push a goal into the in-memory goal stack."""
        host = cast(_L0GoalHostProtocol, self)
        await host.start_session(session_id=session_id)
        now = time.time()
        goal = {
            "goal_id": goal_id,
            "parent_goal_id": parent_goal_id,
            "goal_type": goal_type,
            "description": description,
            "status": status,
            "priority": int(priority),
            "created_at": now,
            "started_at": now if status == "in_progress" else None,
            "completed_at": None,
            "result_summary": None,
            "metadata": dict(metadata or {}),
        }
        host._goal_stack[session_id].append(goal)
        return goal

    def push_goal_sync(
        self,
        *,
        session_id: str,
        goal_id: str,
        goal_type: str,
        description: str,
        status: str = "pending",
        priority: int = 0,
        parent_goal_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Synchronously push a goal into the in-memory goal stack."""
        host = cast(_L0GoalHostProtocol, self)
        host._ensure_session_sync(session_id)
        now = time.time()
        goal = {
            "goal_id": goal_id,
            "parent_goal_id": parent_goal_id,
            "goal_type": goal_type,
            "description": description,
            "status": status,
            "priority": int(priority),
            "created_at": now,
            "started_at": now if status == "in_progress" else None,
            "completed_at": None,
            "result_summary": None,
            "metadata": dict(metadata or {}),
        }
        host._goal_stack[session_id].append(goal)
        return dict(goal)

    async def set_goal_status(
        self,
        *,
        session_id: str,
        goal_id: str,
        status: str,
        result_summary: Optional[str] = None,
    ) -> bool:
        """Update the status of an existing goal."""
        return self.set_goal_status_sync(
            session_id=session_id,
            goal_id=goal_id,
            status=status,
            result_summary=result_summary,
        )

    def set_goal_status_sync(
        self,
        *,
        session_id: str,
        goal_id: str,
        status: str,
        result_summary: Optional[str] = None,
    ) -> bool:
        """Synchronously update the status of an existing goal."""
        host = cast(_L0GoalHostProtocol, self)
        goals = host._goal_stack.get(session_id, [])
        for goal in goals:
            if goal["goal_id"] != goal_id:
                continue
            goal["status"] = status
            if status == "in_progress" and goal["started_at"] is None:
                goal["started_at"] = time.time()
            if status in {"completed", "failed", "cancelled"}:
                goal["completed_at"] = time.time()
            if result_summary is not None:
                goal["result_summary"] = result_summary
            return True
        return False


__all__ = ["L0GoalStackMixin"]
