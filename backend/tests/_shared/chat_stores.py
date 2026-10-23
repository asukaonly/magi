"""Explicit test composition for chat persistence and cross-domain cleanup."""

from typing import Any

from magi.chat.service import ChatService as ChatReadService
from magi.chat.storage.relational_reader import RelationalChatReadRepository
from magi.chat.asset_gc import ChatAssetGC
from magi.runtime_trace.persistence.chat_cleanup import SqliteTraceContentRepository
from magi.chat.storage.workspace_preferences import JsonRecentWorkspaceRepository
from magi.utils.runtime import get_runtime_paths
from magi.chat.storage.sqlite_database import SqliteChatReadDatabase


def build_chat_reader(**options: Any) -> ChatReadService:
    paths = options.setdefault("runtime_paths", get_runtime_paths())
    options.setdefault("database", SqliteChatReadDatabase(paths.chat_db_path))
    options.setdefault("trace_content", SqliteTraceContentRepository(paths.runtime_trace_db_path))
    options.setdefault("workspace_preferences", JsonRecentWorkspaceRepository(paths.config_dir / "recent_chat_workspaces.json"))
    options.pop("runtime_paths")
    database = options.pop("database")
    preferences = options.pop("workspace_preferences")
    assets = ChatAssetGC(runtime_paths=paths)
    return ChatReadService(repository=RelationalChatReadRepository(
        database=database, workspace_preferences=preferences, asset_inventory=assets),
        asset_gc=assets, runtime_paths=paths, **options)


def build_chat_asset_gc(**options: Any):
    from magi.chat.asset_gc import ChatAssetGC
    paths = options.setdefault("runtime_paths", get_runtime_paths())
    options.setdefault("ownership", build_chat_reader(runtime_paths=paths))
    return ChatAssetGC(**options)
