"""Container-backed runtime binding helpers for API and transport consumers."""

from __future__ import annotations

from typing import Any

from .container import get_container


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


def _require_binding(provider_name: str):
    container = get_container()
    provider = getattr(container, provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def require_runtime_command_queue():
    """Return the active runtime command queue binding."""
    return _require_binding("runtime_command_queue")


def require_agent_runtime():
    """Return the active agent runtime binding."""
    return _require_binding("agent_runtime")


def get_optional_agent_runtime() -> Any | None:
    """Return the active agent runtime binding, or ``None`` before startup."""
    container = get_container()
    provider = container.agent_runtime
    instance = provider()
    if instance is None:
        return None
    if type(instance).__name__ == "object" and not provider.overridden:
        return None
    return instance


def require_scheduler_service():
    """Return the active scheduler service binding."""
    return _require_binding("scheduler_service")


def require_chat_portrait_service():
    """Return the active chat portrait service binding."""
    return _require_binding("chat_portrait_service")


def require_chat_read_service():
    """Return the active chat read service binding."""
    return _require_binding("chat_read_service")


def require_chat_attachment_ingestion_service():
    """Return the active chat attachment ingestion service binding."""
    return _require_binding("chat_attachment_ingestion_service")


def require_chat_surface_write_service():
    """Return the active chat surface write service binding."""
    return _require_binding("chat_surface_write_service")


def get_chat_message_notifier():
    """Return the active chat message notifier, or a no-op fallback."""
    container = get_container()
    provider = container.chat_message_notifier
    instance = provider()
    if instance is None:
        return _NOOP_CHAT_MESSAGE_NOTIFIER
    if type(instance).__name__ == "object" and not provider.overridden:
        return _NOOP_CHAT_MESSAGE_NOTIFIER
    return instance


def require_user_message_dispatcher():
    """Return the active user-message dispatcher binding."""
    return _require_binding("user_message_dispatcher")
