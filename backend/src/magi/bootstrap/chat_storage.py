"""Select and own chat persistence at the composition boundary."""

import asyncio
from dataclasses import dataclass

from ..chat.ports import ChatRepository
from ..chat.read_ports import ChatApplication
from ..chat.service import ChatService
from ..chat.asset_gc import ChatAssetGC
from ..chat.storage_snapshot import ChatStateTransfer
from ..chat.storage.relational import ChatDatabase, ChatReadDatabase
from ..chat.storage.relational_store import RelationalChatRepository
from ..chat.storage.relational_reader import RelationalChatReadRepository
from ..chat.storage.snapshots import RelationalChatStateTransfer
from ..chat.storage.sqlite_database import SqliteChatDatabase, SqliteChatReadDatabase
from ..chat.storage.mysql.database import MysqlChatDatabase
from ..chat.storage.mysql.read_database import MysqlChatReadDatabase
from ..chat.storage.workspace_preferences import JsonRecentWorkspaceRepository
from ..config.storage_models import StructuredStorageSettings
from ..core.async_cleanup import finish_cleanup
from ..db.mysql import MysqlDatabase
from ..db.mysql_migrations import upgrade_mysql_chat
from ..runtime_trace.persistence.chat_cleanup import SqliteTraceContentRepository
from ..utils.runtime import RuntimePaths
from .chat_storage_transfer import binding_file, preflight_storage_selection, storage_target


@dataclass
class ChatStorageRuntime:
    store: ChatRepository
    reader: ChatApplication
    state_transfer: ChatStateTransfer
    read_pool: MysqlChatReadDatabase | None = None

    async def close(self) -> None:
        try:
            await self.store.shutdown()
            await finish_cleanup(asyncio.to_thread(self.reader.close))
        finally:
            if self.read_pool is not None:
                await finish_cleanup(asyncio.to_thread(self.read_pool.close))


async def compose_chat_storage(
    paths: RuntimePaths, settings: StructuredStorageSettings, mysql: MysqlDatabase | None
) -> ChatStorageRuntime:
    binding = await preflight_storage_selection(paths, settings.chat, settings.mysql)
    writes: ChatDatabase
    reads: ChatReadDatabase
    read_pool = None
    if settings.chat == "sqlite":
        writes = SqliteChatDatabase(paths.chat_db_path)
        reads = SqliteChatReadDatabase(paths.chat_db_path)
    else:
        if mysql is None or settings.mysql is None:
            raise RuntimeError("MySQL chat storage requires managed connections")
        await upgrade_mysql_chat(mysql)
        writes = MysqlChatDatabase(mysql, center_id=binding.center_id)
        read_pool = MysqlChatReadDatabase(settings.mysql, center_id=binding.center_id)
        reads = read_pool
    assets = ChatAssetGC(runtime_paths=paths)
    runtime = ChatStorageRuntime(
        store=RelationalChatRepository(database=writes, runtime_paths=paths),
        reader=ChatService(
            repository=RelationalChatReadRepository(database=reads, asset_inventory=assets,
                workspace_preferences=JsonRecentWorkspaceRepository(paths.config_dir / "recent_chat_workspaces.json")),
            trace_content=SqliteTraceContentRepository(paths.runtime_trace_db_path), asset_gc=assets, runtime_paths=paths,
        ),
        state_transfer=RelationalChatStateTransfer(writes),
        read_pool=read_pool,
    )
    try:
        await runtime.store.initialize()
        await runtime.reader.aget_interrupted_global_clear_count()
        binding.active = storage_target(settings.chat, settings.mysql)
        binding_file(paths).write(binding)
        return runtime
    except BaseException:
        await runtime.close()
        raise
