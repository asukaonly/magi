"""Read turn-bound client context separately from conversational memory."""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from ..core.client_environment import ClientEnvironment, CLIENT_ENVIRONMENT_MAX_AGE_SECONDS
from .store import ChatStore


async def read_client_environment(
    store: ChatStore,
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
) -> dict[str, Any]:
    """Read only this owner's accepted turn; never borrow another turn's device."""
    unavailable = {
        "status": "unknown",
        "source": "client_reported",
        "subject": "interaction_client",
    }
    if not user_id or not session_id or not turn_id:
        return unavailable
    record = await store.get_user_turn_delivery(turn_id=turn_id)
    if record is None or record.user_id != user_id or record.session_id != session_id:
        return unavailable
    value = record.runtime_envelope.get("client_environment")
    if value is None:
        return unavailable
    try:
        environment = ClientEnvironment.model_validate(value)
    except ValidationError:
        return unavailable
    received_at = record.created_at_ms / 1000
    age = time.time() - received_at
    expires_at = received_at + CLIENT_ENVIRONMENT_MAX_AGE_SECONDS
    return {
        **environment.model_dump(),
        "status": "available" if 0 <= age < CLIENT_ENVIRONMENT_MAX_AGE_SECONDS else "stale",
        "source": "client_reported",
        "subject": "interaction_client",
        "received_at": received_at,
        "expires_at": expires_at,
    }
