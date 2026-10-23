"""Container-backed providers for chat-domain runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..core.container import require_binding, optional_binding

if TYPE_CHECKING:
    from .projector import ChatProjector
    from .store import ChatStore

def get_chat_store() -> "ChatStore":
    """Return the active chat store binding."""
    return cast("ChatStore", require_binding("chat_store"))


def get_chat_projector() -> "ChatProjector":
    """Return the active chat projector binding."""
    return cast("ChatProjector", require_binding("chat_projector"))


class _NoopChatMessageNotifier:
    async def broadcast_chat_message_upsert(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> None:
        return None

    async def broadcast_chat_message_hidden(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> None:
        return None

_NOOP_CHAT_MESSAGE_NOTIFIER = _NoopChatMessageNotifier()


def get_chat_message_notifier() -> Any:
    return optional_binding("chat_message_notifier") or _NOOP_CHAT_MESSAGE_NOTIFIER

def require_chat_read_service():
    """Return the active chat read service binding."""
    return require_binding("chat_read_service")

def require_chat_surface_write_service():
    """Return the active chat surface write service binding."""
    return require_binding("chat_surface_write_service")

def require_user_message_dispatcher():
    """Return the active user-message dispatcher binding."""
    return require_binding("user_message_dispatcher")
