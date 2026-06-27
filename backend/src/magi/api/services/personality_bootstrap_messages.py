"""Persistence helpers for persona bootstrap chat messages."""

from __future__ import annotations

from ...core.runtime_bindings import require_chat_surface_write_service


async def persist_bootstrap_assistant_message(
    *,
    session_id: str,
    user_id: str,
    turn_id: str,
    content: str,
) -> str:
    """Persist a bootstrap assistant reply as a chat message and emit a notification."""
    return await require_chat_surface_write_service().persist_bootstrap_assistant_message(
        session_id=session_id,
        user_id=user_id,
        turn_id=turn_id,
        content=content,
    )


__all__ = ["persist_bootstrap_assistant_message"]
