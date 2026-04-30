"""Container-backed providers for chat-domain runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..core.container import get_container

if TYPE_CHECKING:
    from .projector import ChatProjector
    from .store import ChatStore

def _require_chat_binding(provider_name: str) -> Any:
    provider = getattr(get_container(), provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def get_chat_store() -> "ChatStore":
    """Return the active chat store binding."""
    return cast("ChatStore", _require_chat_binding("chat_store"))


def get_chat_projector() -> "ChatProjector":
    """Return the active chat projector binding."""
    return cast("ChatProjector", _require_chat_binding("chat_projector"))
