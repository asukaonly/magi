"""SQLite composition for the shared chat transaction implementation."""

from pathlib import Path
from magi_plugin_sdk.runtime_paths import get_magi_home
from ...utils.runtime import RuntimePaths, get_runtime_paths
from .relational_store import RelationalChatRepository
from .sqlite_database import SqliteChatDatabase


class SqliteChatRepository(RelationalChatRepository):
    """Bind chat transactions to the local SQLite database."""

    def __init__(self, *, db_path: str = str(get_magi_home() / "data/chat/chat.db"),
                 runtime_paths: RuntimePaths | None = None) -> None:
        self.db_path = str(Path(db_path).expanduser())
        super().__init__(database=SqliteChatDatabase(self.db_path),
                         runtime_paths=runtime_paths or _runtime_paths_for_chat_db(self.db_path))


def _runtime_paths_for_chat_db(db_path: str) -> RuntimePaths:
    expanded = Path(db_path).expanduser().absolute()
    if expanded.name == "chat.db" and expanded.parent.name == "chat" and expanded.parent.parent.name == "data":
        return RuntimePaths(base_dir=expanded.parents[2])
    return get_runtime_paths()
