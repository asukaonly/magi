"""Select concrete chat persistence at the composition boundary."""

from ..chat.ports import ChatRepository
from ..chat.storage.sqlite_database import SqliteChatReadDatabase
from ..chat.read_ports import ChatReadRepository
from ..chat.storage.sqlite_store import SqliteChatRepository
from ..chat.storage.relational_reader import RelationalChatReadRepository
from ..chat.storage.workspace_preferences import JsonRecentWorkspaceRepository
from ..runtime_trace.persistence.chat_cleanup import SqliteTraceContentRepository
from ..utils.runtime import RuntimePaths


def compose_chat_repository(paths: RuntimePaths) -> ChatRepository:
    return SqliteChatRepository(db_path=str(paths.chat_db_path), runtime_paths=paths)


def compose_chat_reader(paths: RuntimePaths) -> ChatReadRepository:
    return RelationalChatReadRepository(
        database=SqliteChatReadDatabase(paths.chat_db_path),
        runtime_paths=paths,
        trace_content=SqliteTraceContentRepository(paths.runtime_trace_db_path),
        workspace_preferences=JsonRecentWorkspaceRepository(paths.config_dir / "recent_chat_workspaces.json"),
    )
