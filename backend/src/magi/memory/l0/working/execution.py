"""Execution-lane state operations for L0 working memory."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Protocol


class _L0ExecutionHostProtocol(Protocol):
    _execution_runs: dict[str, dict[str, Any]]
    _execution_pending_turns: dict[str, list[dict[str, Any]]]
    _execution_results: dict[str, list[dict[str, Any]]]

    async def start_session(
        self,
        *,
        session_id: str,
        user_id: Optional[str] = None,
        runtime_agent_id: Optional[str] = None,
        status: str = "active",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]: ...

    def _ensure_session_sync(self, session_id: str) -> dict[str, Any]: ...


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
        """Synchronously append one pending user turn to the execution lane."""
        host = self._l0_execution_host()
        host._ensure_session_sync(session_id)
        normalized_disposition = str(disposition or "augment").strip().lower()
        if normalized_disposition not in {"augment", "defer", "steer"}:
            normalized_disposition = "augment"
        pending_turn = {
            "session_id": session_id,
            "run_id": run_id,
            "turn_id": turn_id,
            "content": content,
            "revision": int(revision),
            "disposition": normalized_disposition,
            "created_at": time.time(),
        }
        host._execution_pending_turns.setdefault(session_id, []).append(pending_turn)
        return dict(pending_turn)

    def consume_execution_pending_turns_sync(
        self,
        session_id: str,
        *,
        revision: int | None = None,
        disposition: str | None = None,
    ) -> list[dict[str, Any]]:
        """Synchronously return and clear pending execution turns for a session.

        Filters may be combined. When provided, only turns matching *both*
        revision and disposition are consumed; non-matching turns stay queued.
        """
        host = self._l0_execution_host()
        existing = host._execution_pending_turns.get(session_id, [])

        target_revision = int(revision) if revision is not None else None
        target_disposition = str(disposition).strip().lower() if disposition is not None else None

        def _matches(item: dict[str, Any]) -> bool:
            if target_revision is not None:
                item_revision = item.get("revision")
                if item_revision is None or int(item_revision) != target_revision:
                    return False
            if target_disposition is not None:
                item_disposition = str(item.get("disposition") or "augment").strip().lower()
                if item_disposition != target_disposition:
                    return False
            return True

        pending_turns = [dict(item) for item in existing if _matches(item)]
        host._execution_pending_turns[session_id] = [
            item for item in existing if not _matches(item)
        ]
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
        return dict(result)

    def clear_execution_state_sync(self, session_id: str) -> None:
        """Synchronously clear all execution-lane state for one session."""
        host = self._l0_execution_host()
        host._execution_runs.pop(session_id, None)
        host._execution_pending_turns.pop(session_id, None)
        host._execution_results.pop(session_id, None)

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
