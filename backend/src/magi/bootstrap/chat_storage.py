"""Select concrete chat persistence at the composition boundary."""

from ..chat.ports import ChatRepository
from ..chat.storage.sqlite_store import SqliteChatRepository
from ..utils.runtime import RuntimePaths


def compose_chat_repository(paths: RuntimePaths) -> ChatRepository:
    return SqliteChatRepository(db_path=str(paths.chat_db_path), runtime_paths=paths)
