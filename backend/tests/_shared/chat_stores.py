"""Explicit test composition for chat persistence and cross-domain cleanup."""

from typing import Any

from magi.chat.storage.sqlite_reader import SqliteChatReadRepository as ChatReadService
from magi.runtime_trace.persistence.chat_cleanup import SqliteTraceContentRepository
from magi.chat.storage.workspace_preferences import JsonRecentWorkspaceRepository
from magi.utils.runtime import get_runtime_paths


def build_chat_reader(**options: Any) -> ChatReadService:
    paths = options.setdefault("runtime_paths", get_runtime_paths())
    options.setdefault("trace_content", SqliteTraceContentRepository(paths.runtime_trace_db_path))
    options.setdefault("workspace_preferences", JsonRecentWorkspaceRepository(paths.config_dir / "recent_chat_workspaces.json"))
    return ChatReadService(**options)
