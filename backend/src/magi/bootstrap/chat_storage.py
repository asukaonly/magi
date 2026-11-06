"""Compose chat services from the selected plugin repository session."""

from dataclasses import dataclass
from ..chat.ports import ChatRepository
from ..chat.read_ports import ChatApplication
from ..chat.service import ChatService
from ..chat.asset_gc import ChatAssetGC
from ..chat.storage_snapshot import ChatStateTransfer
from ..chat.storage.host import LocalChatStorageHost
from ..chat.storage.plugin_proxy import ChatStorageProxy
from ..chat.storage.workspace_preferences import JsonRecentWorkspaceRepository
from ..runtime_trace.persistence.chat_cleanup import SqliteTraceContentRepository
from ..utils.runtime import RuntimePaths
from .storage_selection import OpenStorage


@dataclass
class ChatStorageRuntime:
    store: ChatRepository
    reader: ChatApplication
    state_transfer: ChatStateTransfer

    async def close(self) -> None:
        await self.store.shutdown()
        self.reader.close()


def compose_chat_storage(paths: RuntimePaths, selected: OpenStorage) -> ChatStorageRuntime:
    assets = ChatAssetGC(runtime_paths=paths)
    host = LocalChatStorageHost(paths, assets=assets)
    preferences = JsonRecentWorkspaceRepository(paths.config_dir / "recent_chat_workspaces.json")
    store = ChatStorageProxy(selected.entry.provider, selected.opened.session_id, repository="chat", host=host)
    reads = ChatStorageProxy(selected.entry.provider, selected.opened.session_id,
                             repository="reads", host=host, workspace_preferences=preferences)
    return ChatStorageRuntime(store, ChatService(repository=reads,
        trace_content=SqliteTraceContentRepository(paths.runtime_trace_db_path), asset_gc=assets, runtime_paths=paths), selected.transfer)
