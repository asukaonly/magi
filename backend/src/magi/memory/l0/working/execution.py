"""Execution-lane state operations for L0 working memory."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional, Protocol

from ....core.sqlite import sqlite_connection_async


class _L0ExecutionHostProtocol(Protocol):
    _execution_runs: dict[str, dict[str, Any]]
    _execution_pending_turns: dict[str, list[dict[str, Any]]]
    _execution_results: dict[str, list[dict[str, Any]]]
    _goal_stack: dict[str, list[dict[str, Any]]]
    _checkpoint_lock: asyncio.Lock
    checkpoint_db_path: str

    async def start_session(
        self,
        *,
        session_id: str,
        user_id: Optional[str] = None,
        runtime_agent_id: Optional[str] = None,
        status: str = "active",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]: ...

    async def initialize(self) -> None: ...

    def _ensure_session_sync(self, session_id: str) -> dict[str, Any]: ...

    def _schedule_checkpoint(self, session_id: str) -> None: ...


def _execution_goal_owned_by_turn(
    goal: dict[str, Any],
    *,
    turn_id: str,
    root_run_revisions: set[tuple[str, int]],
) -> bool:
    if str(goal.get("goal_type") or "") != "chat_run":
        return False
    metadata = goal.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    if str(metadata.get("root_turn_id") or "") == turn_id:
        return True
    goal_id = str(goal.get("goal_id") or "")
    if any(
        goal_id == f"chat_run:{owned_run_id}:{owned_revision}"
        for owned_run_id, owned_revision in root_run_revisions
    ):
        return True
    run_id = str(metadata.get("run_id") or "")
    try:
        revision = int(metadata.get("revision") or 0)
    except (TypeError, ValueError):
        return False
    return (run_id, revision) in root_run_revisions


def _execution_result_owned_by_turn(
    result: dict[str, Any],
    *,
    turn_id: str,
) -> bool:
    payload = result.get("payload")
    return isinstance(payload, dict) and str(payload.get("turn_id") or "") == turn_id


class L0ExecutionStateMixin:
    """Maintain active execution run, pending turns, and execution results."""

    async def upsert_execution_run(
        self,
        *,
        session_id: str,
        run_id: str,
        status: str,
        revision: int,
        root_turn_id: Optional[str] = None,
        root_user_message: str = "",
        response_anchor_turn_id: Optional[str] = None,
        cancel_requested_at: Optional[float] = None,
        cancel_reason: Optional[str] = None,
        cancel_requested_by: Optional[str] = None,
        cancel_anchor_turn_id: Optional[str] = None,
        trigger_dict: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Upsert the active execution run for a session."""
        host = self._l0_execution_host()
        await host.start_session(session_id=session_id)
        return self.upsert_execution_run_sync(
            session_id=session_id,
            run_id=run_id,
            status=status,
            revision=revision,
            root_turn_id=root_turn_id,
            root_user_message=root_user_message,
            response_anchor_turn_id=response_anchor_turn_id,
            cancel_requested_at=cancel_requested_at,
            cancel_reason=cancel_reason,
            cancel_requested_by=cancel_requested_by,
            cancel_anchor_turn_id=cancel_anchor_turn_id,
            trigger_dict=trigger_dict,
        )

    async def append_execution_pending_turn(
        self,
        *,
        session_id: str,
        run_id: str,
        turn_id: str,
        content: str,
        revision: int,
        disposition: str = "augment",
    ) -> dict[str, Any]:
        """Append one pending user turn to the execution lane."""
        host = self._l0_execution_host()
        await host.start_session(session_id=session_id)
        return self.append_execution_pending_turn_sync(
            session_id=session_id,
            run_id=run_id,
            turn_id=turn_id,
            content=content,
            revision=revision,
            disposition=disposition,
        )

    async def record_execution_result(
        self,
        *,
        session_id: str,
        run_id: str,
        result_id: str,
        revision: int,
        disposition: str,
        payload: Dict[str, Any],
    ) -> dict[str, Any]:
        """Record one accepted or stale execution result."""
        host = self._l0_execution_host()
        await host.start_session(session_id=session_id)
        return self.record_execution_result_sync(
            session_id=session_id,
            run_id=run_id,
            result_id=result_id,
            revision=revision,
            disposition=disposition,
            payload=payload,
        )

    async def get_execution_state(self, session_id: str) -> dict[str, Any]:
        """Return the restored execution-lane state for one session."""
        return self.get_execution_state_sync(session_id)

    async def forget_execution_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> dict[str, int]:
        """Remove only execution state owned by one forgotten user turn."""
        host = self._l0_execution_host()
        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_session_id or not normalized_turn_id:
            raise ValueError("session_id and turn_id must not be empty")
        await host.initialize()

        async with host._checkpoint_lock:
            live_run = host._execution_runs.get(normalized_session_id)
            root_run_revisions: set[tuple[str, int]] = set()
            whole_run_ids: set[str] = set()
            live_root_owned = (
                live_run is not None
                and str(live_run.get("root_turn_id") or "") == normalized_turn_id
            )
            if live_root_owned and live_run is not None:
                live_identity = (
                    str(live_run.get("run_id") or ""),
                    int(live_run.get("revision") or 0),
                )
                if live_identity[0]:
                    root_run_revisions.add(live_identity)
                    whole_run_ids.add(live_identity[0])
            pending_pairs = {
                (str(item.get("run_id") or ""), int(item.get("revision") or 0))
                for item in host._execution_pending_turns.get(normalized_session_id, ())
                if str(item.get("turn_id") or "") == normalized_turn_id
            }
            owned_result_ids: set[str] = set()

            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    async with db.execute(
                        """
                        SELECT run_id, revision
                        FROM l0_execution_runs
                        WHERE session_id = ? AND root_turn_id = ?
                        LIMIT 1
                        """,
                        (normalized_session_id, normalized_turn_id),
                    ) as cursor:
                        durable_root = await cursor.fetchone()
                    if durable_root is not None:
                        durable_identity = (
                            str(durable_root[0] or ""),
                            int(durable_root[1] or 0),
                        )
                        if durable_identity[0]:
                            root_run_revisions.add(durable_identity)

                    async with db.execute(
                        """
                        SELECT stack_id, goal_id, goal_type, metadata
                        FROM l0_goal_stack
                        WHERE session_id = ? AND goal_type = 'chat_run'
                        """,
                        (normalized_session_id,),
                    ) as cursor:
                        durable_goals = await cursor.fetchall()
                    owned_goal_stack_ids: list[int] = []
                    for row in durable_goals:
                        try:
                            metadata = json.loads(str(row[3] or "{}"))
                        except (TypeError, ValueError):
                            metadata = {}
                        goal = {
                            "goal_id": str(row[1] or ""),
                            "goal_type": str(row[2] or ""),
                            "metadata": metadata,
                        }
                        if _execution_goal_owned_by_turn(
                            goal,
                            turn_id=normalized_turn_id,
                            root_run_revisions=root_run_revisions,
                        ):
                            owned_goal_stack_ids.append(int(row[0]))

                    async with db.execute(
                        """
                        SELECT run_id, revision
                        FROM l0_execution_pending_turns
                        WHERE session_id = ? AND turn_id = ?
                        """,
                        (normalized_session_id, normalized_turn_id),
                    ) as cursor:
                        pending_pairs.update(
                            (str(row[0] or ""), int(row[1] or 0))
                            for row in await cursor.fetchall()
                        )

                    async with db.execute(
                        """
                        SELECT result_id, payload_json
                        FROM l0_execution_results
                        WHERE session_id = ?
                        """,
                        (normalized_session_id,),
                    ) as cursor:
                        durable_results = await cursor.fetchall()
                    for row in durable_results:
                        try:
                            payload = json.loads(str(row[1] or "{}"))
                        except (TypeError, ValueError):
                            payload = {}
                        if _execution_result_owned_by_turn(
                            {"payload": payload},
                            turn_id=normalized_turn_id,
                        ):
                            owned_result_ids.add(str(row[0] or ""))
                    owned_result_ids.discard("")

                    await db.execute(
                        """
                        DELETE FROM l0_execution_runs
                        WHERE session_id = ? AND root_turn_id = ?
                        """,
                        (normalized_session_id, normalized_turn_id),
                    )
                    await db.execute(
                        """
                        DELETE FROM l0_execution_pending_turns
                        WHERE session_id = ? AND turn_id = ?
                        """,
                        (normalized_session_id, normalized_turn_id),
                    )
                    if owned_goal_stack_ids:
                        await db.executemany(
                            "DELETE FROM l0_goal_stack WHERE stack_id = ?",
                            [(stack_id,) for stack_id in owned_goal_stack_ids],
                        )
                    if whole_run_ids:
                        await db.executemany(
                            """
                            DELETE FROM l0_execution_pending_turns
                            WHERE session_id = ? AND run_id = ?
                            """,
                            [
                                (normalized_session_id, run_id)
                                for run_id in sorted(whole_run_ids)
                            ],
                        )
                        await db.executemany(
                            """
                            DELETE FROM l0_execution_results
                            WHERE session_id = ? AND run_id = ?
                            """,
                            [
                                (normalized_session_id, run_id)
                                for run_id in sorted(whole_run_ids)
                            ],
                        )
                    exact_root_revisions = sorted(
                        (run_id, revision)
                        for run_id, revision in root_run_revisions
                        if run_id not in whole_run_ids
                    )
                    if exact_root_revisions:
                        await db.executemany(
                            """
                            DELETE FROM l0_execution_pending_turns
                            WHERE session_id = ? AND run_id = ? AND revision = ?
                            """,
                            [
                                (normalized_session_id, run_id, revision)
                                for run_id, revision in exact_root_revisions
                            ],
                        )
                        await db.executemany(
                            """
                            DELETE FROM l0_execution_results
                            WHERE session_id = ? AND run_id = ? AND revision = ?
                            """,
                            [
                                (normalized_session_id, run_id, revision)
                                for run_id, revision in exact_root_revisions
                            ],
                        )
                    if owned_result_ids:
                        await db.executemany(
                            """
                            DELETE FROM l0_execution_results
                            WHERE session_id = ? AND result_id = ?
                            """,
                            [
                                (normalized_session_id, result_id)
                                for result_id in sorted(owned_result_ids)
                            ],
                        )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise

            current_run = host._execution_runs.get(normalized_session_id)
            if (
                current_run is not None
                and str(current_run.get("root_turn_id") or "") == normalized_turn_id
            ):
                current_identity = (
                    str(current_run.get("run_id") or ""),
                    int(current_run.get("revision") or 0),
                )
                if current_identity[0]:
                    root_run_revisions.add(current_identity)
                    whole_run_ids.add(current_identity[0])
                host._execution_runs.pop(normalized_session_id, None)
            goals = host._goal_stack.get(normalized_session_id, [])
            host._goal_stack[normalized_session_id] = [
                goal
                for goal in goals
                if not _execution_goal_owned_by_turn(
                    goal,
                    turn_id=normalized_turn_id,
                    root_run_revisions=root_run_revisions,
                )
            ]
            pending = host._execution_pending_turns.get(normalized_session_id, [])
            pending_pairs.update(
                (str(item.get("run_id") or ""), int(item.get("revision") or 0))
                for item in pending
                if str(item.get("turn_id") or "") == normalized_turn_id
            )
            host._execution_pending_turns[normalized_session_id] = [
                item
                for item in pending
                if str(item.get("run_id") or "") not in whole_run_ids
                and (
                    str(item.get("run_id") or ""),
                    int(item.get("revision") or 0),
                )
                not in root_run_revisions
                and str(item.get("turn_id") or "") != normalized_turn_id
            ]
            results = host._execution_results.get(normalized_session_id, [])
            owned_result_ids.update(
                str(item.get("result_id") or "")
                for item in results
                if _execution_result_owned_by_turn(
                    item,
                    turn_id=normalized_turn_id,
                )
            )
            owned_result_ids.discard("")
            if whole_run_ids or root_run_revisions or owned_result_ids:
                host._execution_results[normalized_session_id] = [
                    item
                    for item in results
                    if str(item.get("run_id") or "") not in whole_run_ids
                    and (
                        str(item.get("run_id") or ""),
                        int(item.get("revision") or 0),
                    )
                    not in root_run_revisions
                    and str(item.get("result_id") or "") not in owned_result_ids
                ]
            return {
                "execution_runs": len(root_run_revisions),
                "execution_pending_turns": len(pending_pairs),
                "execution_goals": len(goals)
                - len(host._goal_stack[normalized_session_id]),
            }

    def upsert_execution_run_sync(
        self,
        *,
        session_id: str,
        run_id: str,
        status: str,
        revision: int,
        root_turn_id: Optional[str] = None,
        root_user_message: str = "",
        response_anchor_turn_id: Optional[str] = None,
        cancel_requested_at: Optional[float] = None,
        cancel_reason: Optional[str] = None,
        cancel_requested_by: Optional[str] = None,
        cancel_anchor_turn_id: Optional[str] = None,
        trigger_dict: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Synchronously upsert the active execution run for a session."""
        host = self._l0_execution_host()
        host._ensure_session_sync(session_id)
        existing = host._execution_runs.get(session_id)
        now = time.time()
        execution_run = self._build_execution_run_state(
            session_id=session_id,
            run_id=run_id,
            status=status,
            revision=revision,
            root_turn_id=root_turn_id,
            root_user_message=root_user_message,
            response_anchor_turn_id=response_anchor_turn_id,
            cancel_requested_at=cancel_requested_at,
            cancel_reason=cancel_reason,
            cancel_requested_by=cancel_requested_by,
            cancel_anchor_turn_id=cancel_anchor_turn_id,
            trigger_dict=trigger_dict,
            existing=existing,
            now=now,
        )
        host._execution_runs[session_id] = execution_run
        host._execution_pending_turns.setdefault(session_id, [])
        host._execution_results.setdefault(session_id, [])
        host._schedule_checkpoint(session_id)
        return dict(execution_run)

    @classmethod
    def _build_execution_run_state(
        cls,
        *,
        session_id: str,
        run_id: str,
        status: str,
        revision: int,
        root_turn_id: Optional[str],
        root_user_message: str,
        response_anchor_turn_id: Optional[str],
        cancel_requested_at: Optional[float],
        cancel_reason: Optional[str],
        cancel_requested_by: Optional[str],
        cancel_anchor_turn_id: Optional[str],
        trigger_dict: Optional[dict[str, Any]],
        existing: dict[str, Any] | None,
        now: float,
    ) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "run_id": run_id,
            "status": status,
            "revision": int(revision),
            "root_turn_id": root_turn_id,
            "root_user_message": root_user_message,
            "response_anchor_turn_id": response_anchor_turn_id,
            "cancel_requested_at": cls._float_or_existing(
                cancel_requested_at, existing, "cancel_requested_at"
            ),
            "cancel_reason": cls._str_or_existing(cancel_reason, existing, "cancel_reason"),
            "cancel_requested_by": cls._str_or_existing(
                cancel_requested_by, existing, "cancel_requested_by"
            ),
            "cancel_anchor_turn_id": cls._str_or_existing(
                cancel_anchor_turn_id, existing, "cancel_anchor_turn_id"
            ),
            "trigger": cls._trigger_or_existing(trigger_dict, existing),
            "created_at": float(existing["created_at"]) if existing else now,
            "updated_at": now,
        }

    @staticmethod
    def _float_or_existing(
        value: Optional[float],
        existing: dict[str, Any] | None,
        key: str,
    ) -> float | None:
        if value is not None:
            return float(value)
        if existing and existing.get(key) is not None:
            return float(existing[key])
        return None

    @staticmethod
    def _str_or_existing(
        value: Optional[str],
        existing: dict[str, Any] | None,
        key: str,
    ) -> str | None:
        if value is not None:
            return str(value)
        if existing and existing.get(key) is not None:
            return str(existing[key])
        return None

    @staticmethod
    def _trigger_or_existing(
        trigger_dict: Optional[dict[str, Any]],
        existing: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if trigger_dict is not None:
            return dict(trigger_dict)
        # Later cancel / steer updates should not wipe the original run trigger.
        return existing.get("trigger") if existing else None

    def append_execution_pending_turn_sync(
        self,
        *,
        session_id: str,
        run_id: str,
        turn_id: str,
        content: str,
        revision: int,
        disposition: str = "augment",
    ) -> dict[str, Any]:
        """Synchronously append one pending user turn to the execution lane.

        A runtime command may be delivered again after admission succeeds but
        before its acknowledgement is committed.  The durable chat turn ID is
        therefore the idempotency key here: replaying the same turn must return
        the existing pending record instead of creating a second response.
        """
        host = self._l0_execution_host()
        host._ensure_session_sync(session_id)
        normalized_disposition = str(disposition or "augment").strip().lower()
        if normalized_disposition not in {"augment", "defer", "steer"}:
            normalized_disposition = "augment"
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("turn_id must not be empty")
        pending_turns = host._execution_pending_turns.setdefault(session_id, [])
        for existing in pending_turns:
            if str(existing.get("turn_id") or "") != normalized_turn_id:
                continue
            if str(existing.get("content") or "") != str(content):
                raise ValueError(
                    f"Pending turn '{normalized_turn_id}' was replayed with different content"
                )
            return dict(existing)
        pending_turn = {
            "session_id": session_id,
            "run_id": run_id,
            "turn_id": normalized_turn_id,
            "content": content,
            "revision": int(revision),
            "disposition": normalized_disposition,
            "created_at": time.time(),
        }
        pending_turns.append(pending_turn)
        host._schedule_checkpoint(session_id)
        return dict(pending_turn)

    def consume_execution_pending_turns_sync(
        self,
        session_id: str,
        *,
        revision: int | None = None,
        disposition: str | None = None,
        turn_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Synchronously return and clear pending execution turns for a session.

        Filters may be combined. When provided, only turns matching *both*
        revision, disposition, and turn ID are consumed; non-matching turns
        stay queued.
        """
        host = self._l0_execution_host()
        existing = host._execution_pending_turns.get(session_id, [])

        target_revision = int(revision) if revision is not None else None
        target_disposition = str(disposition).strip().lower() if disposition is not None else None
        target_turn_id = str(turn_id).strip() if turn_id is not None else None

        def _matches(item: dict[str, Any]) -> bool:
            if target_revision is not None:
                item_revision = item.get("revision")
                if item_revision is None or int(item_revision) != target_revision:
                    return False
            if target_disposition is not None:
                item_disposition = str(item.get("disposition") or "augment").strip().lower()
                if item_disposition != target_disposition:
                    return False
            if target_turn_id is not None:
                if str(item.get("turn_id") or "").strip() != target_turn_id:
                    return False
            return True

        pending_turns = [dict(item) for item in existing if _matches(item)]
        host._execution_pending_turns[session_id] = [
            item for item in existing if not _matches(item)
        ]
        if pending_turns:
            host._schedule_checkpoint(session_id)
        return pending_turns

    def record_execution_result_sync(
        self,
        *,
        session_id: str,
        run_id: str,
        result_id: str,
        revision: int,
        disposition: str,
        payload: Dict[str, Any],
    ) -> dict[str, Any]:
        """Synchronously record one accepted or stale execution result."""
        host = self._l0_execution_host()
        host._ensure_session_sync(session_id)
        result = {
            "result_id": result_id,
            "session_id": session_id,
            "run_id": run_id,
            "revision": int(revision),
            "disposition": disposition,
            "payload": dict(payload),
            "created_at": time.time(),
        }
        results = host._execution_results.setdefault(session_id, [])
        results[:] = [item for item in results if str(item.get("result_id")) != result_id]
        results.append(result)
        host._schedule_checkpoint(session_id)
        return dict(result)

    def clear_execution_state_sync(self, session_id: str) -> None:
        """Synchronously clear all execution-lane state for one session."""
        host = self._l0_execution_host()
        host._execution_runs.pop(session_id, None)
        host._execution_pending_turns.pop(session_id, None)
        host._execution_results.pop(session_id, None)
        host._schedule_checkpoint(session_id)

    def get_execution_state_sync(self, session_id: str) -> dict[str, Any]:
        """Synchronously return the execution-lane state for one session."""
        host = self._l0_execution_host()
        run = host._execution_runs.get(session_id)
        pending_turns = [dict(item) for item in host._execution_pending_turns.get(session_id, [])]
        results = [dict(item) for item in host._execution_results.get(session_id, [])]
        return {
            "run": dict(run) if run is not None else None,
            "pending_turns": pending_turns,
            "accepted_results": [
                item for item in results if str(item.get("disposition")) == "accepted"
            ],
            "stale_results": [item for item in results if str(item.get("disposition")) == "stale"],
        }

    def _l0_execution_host(self) -> _L0ExecutionHostProtocol:
        return self  # type: ignore[return-value]


__all__ = ["L0ExecutionStateMixin"]
