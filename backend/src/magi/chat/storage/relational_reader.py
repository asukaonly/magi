"""Compose shared chat queries with local cleanup and trace dependencies."""

from typing import Any

from magi_plugin_sdk.storage_chat.relational_reader import RelationalChatReadRepository as SharedChatReader

from ...utils.runtime import get_runtime_paths
from ..cleanup_plan import ChatAssetInventory
from ..workspace_preferences import RecentWorkspaceRepository
from .host import LocalChatStorageHost
from .relational import ChatReadDatabase

class RelationalChatReadRepository(SharedChatReader):
    def __init__(
        self, *, database: ChatReadDatabase, asset_inventory: ChatAssetInventory,
        workspace_preferences: RecentWorkspaceRepository,
    ) -> None:
        self.workspace_preferences = workspace_preferences
        self._asset_inventory = asset_inventory
        super().__init__(database=database, host=LocalChatStorageHost(
            get_runtime_paths(), assets=asset_inventory, trace=lambda: get_chat_trace_read_service(),
        ))

    def fork(self) -> "RelationalChatReadRepository":
        return RelationalChatReadRepository(
            database=self.database, asset_inventory=self._asset_inventory,
            workspace_preferences=self.workspace_preferences,
        )


def get_chat_trace_read_service() -> Any:
    from ...runtime_trace.chat_trace.read_service import get_chat_trace_read_service as resolve
    return resolve()
