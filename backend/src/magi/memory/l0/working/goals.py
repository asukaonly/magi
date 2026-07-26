"""Goal stack helpers for L0 working memory."""

from __future__ import annotations

import time
import asyncio
from typing import Any, Dict, Optional, Protocol, cast

from ....core.sqlite import sqlite_connection_async

MAX_GOALS_PER_SESSION = 32
TERMINAL_GOAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class _L0GoalHostProtocol(Protocol):
    _goal_stack: dict[str, list[dict[str, Any]]]
    _checkpoint_lock: asyncio.Lock
    checkpoint_db_path: str

    async def start_session(self, *, session_id: str, **kwargs: Any) -> dict[str, Any]: ...

    async def initialize(self) -> None: ...

    def _ensure_session_sync(self, session_id: str) -> dict[str, Any]: ...

    def _schedule_checkpoint(self, session_id: str) -> None: ...


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
        self._store_goal(host, session_id=session_id, goal=goal)
        host._schedule_checkpoint(session_id)
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
        self._store_goal(host, session_id=session_id, goal=goal)
        host._schedule_checkpoint(session_id)
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
            host._schedule_checkpoint(session_id)
            return True
        return False

    def prune_terminal_goals_sync(self, session_id: str) -> int:
        """Remove completed work before a new active run is projected."""

        host = cast(_L0GoalHostProtocol, self)
        goals = host._goal_stack.get(session_id, [])
        retained = [
            goal
            for goal in goals
            if str(goal.get("status") or "") not in TERMINAL_GOAL_STATUSES
        ]
        removed = len(goals) - len(retained)
        if removed:
            host._goal_stack[session_id] = retained
            host._schedule_checkpoint(session_id)
        return removed

    async def forget_chat_turn(self, *, session_id: str, turn_id: str) -> int:
        """Remove chat-run goals owned by one deleted user turn."""

        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_session_id or not normalized_turn_id:
            raise ValueError("session_id and turn_id must not be empty")
        host = cast(_L0GoalHostProtocol, self)
        await host.initialize()
        async with host._checkpoint_lock:
            goals = host._goal_stack.get(normalized_session_id, [])
            retained = [
                goal
                for goal in goals
                if not self._goal_owned_by_turn(goal, normalized_turn_id)
            ]
            removed_live = len(goals) - len(retained)
            host._goal_stack[normalized_session_id] = retained
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                cursor = await db.execute(
                    """
                    DELETE FROM l0_goal_stack
                    WHERE session_id = ?
                      AND goal_type = 'chat_run'
                      AND json_valid(metadata)
                      AND json_extract(metadata, '$.root_turn_id') = ?
                    """,
                    (normalized_session_id, normalized_turn_id),
                )
                await db.commit()
            return max(removed_live, max(int(cursor.rowcount or 0), 0))

    @staticmethod
    def _goal_owned_by_turn(goal: dict[str, Any], turn_id: str) -> bool:
        if str(goal.get("goal_type") or "") != "chat_run":
            return False
        metadata = goal.get("metadata")
        return (
            isinstance(metadata, dict)
            and str(metadata.get("root_turn_id") or "") == turn_id
        )

    @staticmethod
    def _store_goal(
        host: _L0GoalHostProtocol,
        *,
        session_id: str,
        goal: dict[str, Any],
    ) -> None:
        goals = host._goal_stack.setdefault(session_id, [])
        for index, existing in enumerate(goals):
            if str(existing.get("goal_id") or "") == str(goal["goal_id"]):
                goals[index] = goal
                return
        goals.append(goal)
        if len(goals) <= MAX_GOALS_PER_SESSION:
            return
        terminal_indexes = [
            index
            for index, existing in enumerate(goals)
            if str(existing.get("status") or "") in TERMINAL_GOAL_STATUSES
        ]
        while len(goals) > MAX_GOALS_PER_SESSION and terminal_indexes:
            goals.pop(terminal_indexes.pop(0))
            terminal_indexes = [index - 1 for index in terminal_indexes]
        if len(goals) > MAX_GOALS_PER_SESSION:
            del goals[: len(goals) - MAX_GOALS_PER_SESSION]


__all__ = ["L0GoalStackMixin"]
