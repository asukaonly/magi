"""Explicit test composition for chat persistence and cross-domain cleanup."""

from typing import Any

from magi.chat.read_service import ChatReadService
from magi.runtime_trace.persistence.chat_cleanup import SqliteTraceContentRepository
from magi.utils.runtime import get_runtime_paths


def build_chat_reader(**options: Any) -> ChatReadService:
    paths = options.setdefault("runtime_paths", get_runtime_paths())
    options.setdefault("trace_content", SqliteTraceContentRepository(paths.runtime_trace_db_path))
    return ChatReadService(**options)
