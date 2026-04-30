"""Container-backed provider for chat read services."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..read_service import ChatReadService


def get_chat_read_service() -> "ChatReadService":
    """Return the container-owned ChatReadService singleton."""
    from magi.core.container import get_container

    return get_container().chat_read_service()