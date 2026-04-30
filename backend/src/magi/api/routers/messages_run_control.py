"""Run-control routes for active chat sessions."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from .messages_common import legacy_messages_module
from .messages_models import CancelSessionRunRequest, DetachSessionRunRequest

message_run_control_router = APIRouter()


@message_run_control_router.post("/session/{session_id}/cancel-run", response_model=Dict[str, Any])
async def cancel_session_run(session_id: str, request: CancelSessionRunRequest):
    """Explicitly cancel the active run for one chat session."""
    legacy = legacy_messages_module()
    try:
        runtime = legacy.require_agent_runtime()
        manager = runtime.get_task_agent_manager()
        agent = await manager.ensure_agent(legacy.TaskAgentType.CHAT, session_id)
        cancel_handler = getattr(agent, "request_session_cancel", None)
        if cancel_handler is None:
            raise RuntimeError("Chat task agent does not support explicit session cancellation.")
        outcome = await cancel_handler(
            session_id=session_id,
            requested_by=request.requested_by,
            reason=request.reason,
            anchor_turn_id=request.turn_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if outcome is None:
        return {
            "success": False,
            "message": "No active run to cancel",
            "data": {
                "user_id": request.user_id,
                "session_id": session_id,
            },
        }

    return {
        "success": True,
        "message": "Run cancellation requested",
        "data": {
            "user_id": request.user_id,
            "session_id": session_id,
            **dict(outcome),
        },
    }


@message_run_control_router.post("/session/{session_id}/detach-run", response_model=Dict[str, Any])
async def detach_session_run(session_id: str, request: DetachSessionRunRequest):
    """Explicitly request that the active run detach into a background task."""
    legacy = legacy_messages_module()
    try:
        runtime = legacy.require_agent_runtime()
        manager = runtime.get_task_agent_manager()
        agent = await manager.ensure_agent(legacy.TaskAgentType.CHAT, session_id)
        detach_handler = getattr(agent, "request_session_detach", None)
        if detach_handler is None:
            raise RuntimeError("Chat task agent does not support explicit session detaching.")
        outcome = await detach_handler(
            session_id=session_id,
            requested_by=request.requested_by,
            reason=request.reason,
            anchor_turn_id=request.turn_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if outcome is None:
        return {
            "success": False,
            "message": "No active run to detach",
            "data": {
                "user_id": request.user_id,
                "session_id": session_id,
            },
        }

    return {
        "success": True,
        "message": "Run detach requested",
        "data": {
            "user_id": request.user_id,
            "session_id": session_id,
            **dict(outcome),
        },
    }


__all__ = ["cancel_session_run", "detach_session_run", "message_run_control_router"]