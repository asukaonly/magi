"""Native MySQL composition for atomic chat persistence."""

from _shared.mysql_storage_plugin.database import MysqlDatabase
from magi.utils.runtime import RuntimePaths
from magi.chat.storage.relational_store import RelationalChatRepository
from _shared.mysql_storage_plugin.chat.database import MysqlChatDatabase


class MysqlChatRepository(RelationalChatRepository):
    def __init__(self, database: MysqlDatabase, *, center_id: str, runtime_paths: RuntimePaths) -> None:
        super().__init__(database=MysqlChatDatabase(database, center_id=center_id), runtime_paths=runtime_paths)
