"""Payload conversion helpers for chat session runs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from magi_plugin_sdk.run_trigger import RunTrigger

from magi.agent.task_agents.handlers.run_contracts import (
    AgentRun,
    PendingTurn,
    RUN_INPUT_DISPOSITION,
    RUN_PENDING_DISPOSITIONS,
    RunResult,
    RunResultDisposition,
)


class SessionRunConversionMixin:
    """Convert live execution-state payloads to chat run contracts."""

    _execution_store: Any

    def _get_run(self, session_id: str) -> AgentRun | None:
        state = self._execution_store.get_execution_state_sync(session_id)
        run = state.get("run")
        if not isinstance(run, dict):
            return None
        run_id = str(run["run_id"])
        trigger_dict = run.get("trigger")
        trigger = (
            RunTrigger.from_dict(trigger_dict)
            if isinstance(trigger_dict, dict)
            else None
        )
        return AgentRun(
            session_id=str(run["session_id"]),
            run_id=run_id,
            status=str(run.get("status") or "running"),
            root_turn_id=str(run["root_turn_id"]) if run.get("root_turn_id") is not None else None,
            root_user_message=str(run.get("root_user_message") or ""),
            revision=int(run.get("revision") or 0),
            cancel_requested_at=(
                float(run["cancel_requested_at"])
                if run.get("cancel_requested_at") is not None
                else None
            ),
            cancel_reason=str(run["cancel_reason"]) if run.get("cancel_reason") is not None else None,
            cancel_requested_by=(
                str(run["cancel_requested_by"])
                if run.get("cancel_requested_by") is not None
                else None
            ),
            cancel_anchor_turn_id=(
                str(run["cancel_anchor_turn_id"])
                if run.get("cancel_anchor_turn_id") is not None
                else None
            ),
            pending_turns=[self._to_pending_turn(item) for item in state.get("pending_turns", [])],
            accepted_results=[self._to_run_result(item) for item in state.get("accepted_results", [])],
            stale_results=[self._to_run_result(item) for item in state.get("stale_results", [])],
            created_at=float(run.get("created_at") or 0.0),
            updated_at=float(run.get("updated_at") or 0.0),
            trigger=trigger,
        )

    def _require_run(self, session_id: str) -> AgentRun:
        active_run = self._get_run(session_id)
        if active_run is None:
            raise ValueError(f"No active run for session_id={session_id!r}")
        return active_run

    @staticmethod
    def _to_pending_turn(payload: dict[str, Any]) -> PendingTurn:
        disposition = str(
            payload.get("disposition") or RUN_INPUT_DISPOSITION
        ).strip().lower()
        if disposition not in RUN_PENDING_DISPOSITIONS:
            raise ValueError(f"Unsupported pending input disposition: {disposition!r}")
        return PendingTurn(
            turn_id=str(payload["turn_id"]),
            content=str(payload["content"]),
            revision=int(payload["revision"]),
            disposition=disposition,
            created_at=float(payload.get("created_at") or 0.0),
        )

    @staticmethod
    def _to_run_result(payload: dict[str, Any]) -> RunResult:
        return RunResult(
            result_id=str(payload["result_id"]),
            run_id=str(payload["run_id"]),
            revision=int(payload["revision"]),
            payload=deepcopy(payload.get("payload") or {}),
            disposition=RunResultDisposition(str(payload["disposition"])),
            created_at=float(payload.get("created_at") or 0.0),
        )


__all__ = ["SessionRunConversionMixin"]
