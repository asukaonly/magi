"""Authoritative product status reads for independent clients."""

from fastapi import APIRouter, HTTPException

from ...core.client_models import SendConfirmation, SendConfirmationRequest, TurnSnapshot
from ...identity import CANONICAL_LOCAL_USER
from ...control.provider import resolve_control_session_store
from ..runtime_dependencies import require_chat_read_service

message_status_router = APIRouter()


@message_status_router.get("/session/{session_id}/turn/{turn_id}", response_model=TurnSnapshot)
async def get_turn_snapshot(session_id: str, turn_id: str) -> TurnSnapshot:
    try:
        return await require_chat_read_service().aget_turn_snapshot(str(CANONICAL_LOCAL_USER), session_id, turn_id)
    except RuntimeError as exc:
        raise HTTPException(503, "Turn status is unavailable") from exc


@message_status_router.post("/confirmation", response_model=SendConfirmation)
async def confirm_send(body: SendConfirmationRequest) -> SendConfirmation:
    """Read a receipt; this operation never dispatches or retries user work."""
    request = body.root
    if request.kind == "turn":
        snapshot = await get_turn_snapshot(request.session_id, request.turn_id)
        return SendConfirmation(
            session_id=request.session_id, identity=snapshot.turn_id,
            status={"accepted": "confirmed", "absent": "absent", "retired": "concluded"}[snapshot.acceptance],
            safe_to_retry=snapshot.can_resubmit,
        )
    try:
        # Validate session ownership before reading control-domain state.
        session = await require_chat_read_service().aget_session_summary(str(CANONICAL_LOCAL_USER), request.session_id)
        status, retry = ("concluded", False) if session is None else await resolve_control_session_store().confirm_answer(
            request.session_id, request.request_id, request.answer,
        )
    except RuntimeError as exc:
        raise HTTPException(503, "Answer status is unavailable") from exc
    return SendConfirmation(session_id=request.session_id, identity=request.request_id, status=status, safe_to_retry=retry)
