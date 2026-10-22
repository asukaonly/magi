"""Native MySQL composition for atomic chat persistence."""

from ....db.mysql import MysqlDatabase
from ....utils.runtime import RuntimePaths
from ..relational_store import RelationalChatRepository
from .database import MysqlChatDatabase


class MysqlChatRepository(RelationalChatRepository):
    def __init__(self, database: MysqlDatabase, *, center_id: str, runtime_paths: RuntimePaths) -> None:
        super().__init__(database=MysqlChatDatabase(database, center_id=center_id), runtime_paths=runtime_paths)
