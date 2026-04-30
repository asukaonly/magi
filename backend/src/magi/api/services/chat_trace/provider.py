"""Container-backed provider for chat trace read services."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .read_service import ChatTraceReadService


def get_chat_trace_read_service() -> "ChatTraceReadService":
    """Return the container-owned ChatTraceReadService singleton."""
    from ....core.container import get_container

    return get_container().chat_trace_read_service()