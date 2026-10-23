"""Bind command freshness to host-owned durable acceptance records."""
from collections.abc import Callable
from magi.core.tool_context import ToolExecutionContext
from magi.chat.ports import ChatRepository


class CommandAcceptanceResolver:
    def __init__(self, get_chat: Callable[[], ChatRepository | None]) -> None:
        self._get_chat = get_chat

    async def __call__(self, context: ToolExecutionContext) -> int | None:
        identity = context.invocation
        if identity is None:
            return None
        turn_id = context.env_vars.get("turn_id")
        if turn_id:
            chat = self._get_chat()
            turn = await chat.get_turn(turn_id) if chat is not None else None
            if turn is None or turn.session_id != identity.session_id or turn.user_id != identity.principal_id:
                return None
            return int(turn.created_at_ms)
        # Non-chat producers must supply the original host acceptance timestamp.
        # Missing provenance fails closed only for operations declaring freshness.
        return int(identity.accepted_at_ms) if identity.accepted_at_ms is not None else None
