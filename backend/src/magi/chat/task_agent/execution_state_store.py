"""Process-local execution state for one chat task-agent runtime."""

from __future__ import annotations

import time
from typing import Any

MAX_RESULTS_PER_SESSION = 64
RUN_STATUSES = frozenset({"running", "cancelling", "cancelled"})
RESULT_DISPOSITIONS = frozenset({"accepted", "stale"})
PENDING_DISPOSITIONS = frozenset({"message", "replace"})


class SessionExecutionStateStore:
    """Keep live run coordination separate from optional L0 workbench memory.

    Crash recovery is owned by the durable chat delivery ledger. A Python
    process cannot resume live asyncio controls, provider streams, or tool
    calls, so restoring an ``AgentRun`` record without those controls creates
    a ghost run. The delivery ledger redrives every non-terminal turn instead.
    """

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        self._pending_turns: dict[str, list[dict[str, Any]]] = {}
        self._results: dict[str, list[dict[str, Any]]] = {}

    def upsert_execution_run_sync(
        self,
        *,
        session_id: str,
        run_id: str,
        status: str,
        revision: int,
        root_turn_id: str | None = None,
        root_user_message: str = "",
        response_anchor_turn_id: str | None = None,
        cancel_requested_at: float | None = None,
        cancel_reason: str | None = None,
        cancel_requested_by: str | None = None,
        cancel_anchor_turn_id: str | None = None,
        trigger_dict: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_session_id = self._required_text(session_id, "session_id")
        normalized_run_id = self._required_text(run_id, "run_id")
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in RUN_STATUSES:
            raise ValueError(f"Unsupported execution status: {status!r}")

        existing = self._runs.get(normalized_session_id)
        now = time.time()
        reset_cancel_metadata = normalized_status == "running"
        run = {
            "session_id": normalized_session_id,
            "run_id": normalized_run_id,
            "status": normalized_status,
            "revision": int(revision),
            "root_turn_id": self._optional_text(root_turn_id),
            "root_user_message": str(root_user_message or ""),
            "response_anchor_turn_id": self._optional_text(response_anchor_turn_id),
            "cancel_requested_at": (
                None
                if reset_cancel_metadata
                else self._value_or_existing(
                    cancel_requested_at,
                    existing,
                    "cancel_requested_at",
                )
            ),
            "cancel_reason": (
                None
                if reset_cancel_metadata
                else self._value_or_existing(
                    self._optional_text(cancel_reason),
                    existing,
                    "cancel_reason",
                )
            ),
            "cancel_requested_by": (
                None
                if reset_cancel_metadata
                else self._value_or_existing(
                    self._optional_text(cancel_requested_by),
                    existing,
                    "cancel_requested_by",
                )
            ),
            "cancel_anchor_turn_id": (
                None
                if reset_cancel_metadata
                else self._value_or_existing(
                    self._optional_text(cancel_anchor_turn_id),
                    existing,
                    "cancel_anchor_turn_id",
                )
            ),
            "trigger": (
                dict(trigger_dict)
                if trigger_dict is not None
                else dict(existing["trigger"])
                if existing and isinstance(existing.get("trigger"), dict)
                else None
            ),
            "created_at": float(existing["created_at"]) if existing else now,
            "updated_at": now,
        }
        self._runs[normalized_session_id] = run
        self._pending_turns.setdefault(normalized_session_id, [])
        self._results.setdefault(normalized_session_id, [])
        return dict(run)

    def append_execution_pending_turn_sync(
        self,
        *,
        session_id: str,
        run_id: str,
        turn_id: str,
        content: str,
        revision: int,
        disposition: str = "message",
    ) -> dict[str, Any]:
        normalized_session_id = self._required_text(session_id, "session_id")
        normalized_turn_id = self._required_text(turn_id, "turn_id")
        normalized_disposition = str(disposition or "message").strip().lower()
        if normalized_disposition not in PENDING_DISPOSITIONS:
            raise ValueError(f"Unsupported pending-turn disposition: {disposition!r}")

        pending_turns = self._pending_turns.setdefault(normalized_session_id, [])
        for existing in pending_turns:
            if str(existing.get("turn_id") or "") != normalized_turn_id:
                continue
            if str(existing.get("content") or "") != str(content):
                raise ValueError(
                    f"Pending turn '{normalized_turn_id}' was replayed with different content"
                )
            return dict(existing)

        pending_turn = {
            "session_id": normalized_session_id,
            "run_id": self._required_text(run_id, "run_id"),
            "turn_id": normalized_turn_id,
            "content": str(content),
            "revision": int(revision),
            "disposition": normalized_disposition,
            "created_at": time.time(),
        }
        pending_turns.append(pending_turn)
        return dict(pending_turn)

    def consume_execution_pending_turns_sync(
        self,
        session_id: str,
        *,
        revision: int | None = None,
        disposition: str | None = None,
        turn_id: str | None = None,
    ) -> list[dict[str, Any]]:
        existing = self._pending_turns.get(session_id, [])
        target_disposition = (
            str(disposition).strip().lower() if disposition is not None else None
        )
        if (
            target_disposition is not None
            and target_disposition not in PENDING_DISPOSITIONS
        ):
            raise ValueError(
                f"Unsupported pending-turn disposition: {disposition!r}"
            )

        def matches(item: dict[str, Any]) -> bool:
            return (
                (revision is None or int(item.get("revision") or 0) == int(revision))
                and (
                    target_disposition is None
                    or str(item.get("disposition") or "message").strip().lower()
                    == target_disposition
                )
                and (
                    turn_id is None
                    or str(item.get("turn_id") or "").strip() == str(turn_id).strip()
                )
            )

        consumed = [dict(item) for item in existing if matches(item)]
        self._pending_turns[session_id] = [
            item for item in existing if not matches(item)
        ]
        return consumed

    def record_execution_result_sync(
        self,
        *,
        session_id: str,
        run_id: str,
        result_id: str,
        revision: int,
        disposition: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_session_id = self._required_text(session_id, "session_id")
        normalized_result_id = self._required_text(result_id, "result_id")
        normalized_disposition = str(disposition or "").strip().lower()
        if normalized_disposition not in RESULT_DISPOSITIONS:
            raise ValueError(f"Unsupported result disposition: {disposition!r}")
        result = {
            "result_id": normalized_result_id,
            "session_id": normalized_session_id,
            "run_id": self._required_text(run_id, "run_id"),
            "revision": int(revision),
            "disposition": normalized_disposition,
            "payload": dict(payload),
            "created_at": time.time(),
        }
        results = self._results.setdefault(normalized_session_id, [])
        results[:] = [
            item
            for item in results
            if str(item.get("result_id") or "") != normalized_result_id
        ]
        results.append(result)
        if len(results) > MAX_RESULTS_PER_SESSION:
            del results[: len(results) - MAX_RESULTS_PER_SESSION]
        return dict(result)

    def clear_execution_state_sync(self, session_id: str) -> None:
        self._runs.pop(session_id, None)
        self._pending_turns.pop(session_id, None)
        self._results.pop(session_id, None)

    def forget_execution_turn_sync(self, *, session_id: str, turn_id: str) -> None:
        normalized_turn_id = self._required_text(turn_id, "turn_id")
        run = self._runs.get(session_id)
        if run is not None and str(run.get("root_turn_id") or "") == normalized_turn_id:
            self.clear_execution_state_sync(session_id)
            return
        self._pending_turns[session_id] = [
            item
            for item in self._pending_turns.get(session_id, [])
            if str(item.get("turn_id") or "") != normalized_turn_id
        ]
        self._results[session_id] = [
            item
            for item in self._results.get(session_id, [])
            if str((item.get("payload") or {}).get("turn_id") or "")
            != normalized_turn_id
        ]

    def get_execution_state_sync(self, session_id: str) -> dict[str, Any]:
        run = self._runs.get(session_id)
        pending_turns = [
            dict(item) for item in self._pending_turns.get(session_id, [])
        ]
        results = [dict(item) for item in self._results.get(session_id, [])]
        return {
            "run": dict(run) if run is not None else None,
            "pending_turns": pending_turns,
            "accepted_results": [
                item
                for item in results
                if str(item.get("disposition")) == "accepted"
            ],
            "stale_results": [
                item
                for item in results
                if str(item.get("disposition")) == "stale"
            ],
        }

    @staticmethod
    def _required_text(value: Any, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} must not be empty")
        return normalized

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _value_or_existing(
        value: Any,
        existing: dict[str, Any] | None,
        key: str,
    ) -> Any:
        if value is not None:
            return value
        return existing.get(key) if existing else None


__all__ = ["SessionExecutionStateStore"]
