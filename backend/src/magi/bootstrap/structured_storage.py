"""Select storage implementations before channel and memory applications start."""

from ..channels.ports import ChannelRepositories
from ..channels.persistence.session_mappings import SqliteChannelSessionRepository
from ..channels.receipts_store import DeliveryReceiptsStore
from ..channels.binding_settings_store import ChannelBindingSettingsStore
from ..outreach.ports import OutreachRepositories
from ..outreach.stores import OutreachOutboxStore, OutreachDeliveryLogStore
from ..db.mysql import MysqlDatabase
from ..db.mysql_migrations import upgrade_mysql_channels
from ..memory.l1.storage.snapshots import SqliteEventStateTransfer
from ..memory.l1.storage.mysql.snapshots import MysqlEventStateTransfer
from .channel_storage import preflight_storage_selection, verify_storage_selection
from .event_storage import binding_file as event_binding_file
from .event_storage import (
    compose_event_repository,
    preflight_storage_selection as preflight_event_storage,
)
from .context import RuntimeBootstrapContext, require_initialized
from .chat_storage import ChatStorageRuntime, compose_chat_storage
from .chat_storage_transfer import preflight_storage_selection as preflight_chat_storage
from .lifecycle import LifecycleModule


class StructuredStorageModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(name="runtime_structured_storage", dependencies=("runtime_configuration",))
        self._context = context
        self._mysql: MysqlDatabase | None = None
        self._chat: ChatStorageRuntime | None = None

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "configuration")
        paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        settings = config.structured_storage
        await preflight_storage_selection(paths, settings)
        await preflight_event_storage(paths, settings.memory_events, settings.mysql)
        await preflight_chat_storage(paths, settings.chat, settings.mysql)
        try:
            if "mysql" in {settings.channels, settings.memory_events, settings.chat}:
                self._mysql = MysqlDatabase(require_initialized(settings.mysql, "MySQL settings"))
            if settings.channels == "sqlite":
                await verify_storage_selection(paths, settings, None)
                path = str(paths.channels_db_path)
                channels = ChannelRepositories(
                    SqliteChannelSessionRepository(path),
                    DeliveryReceiptsStore(db_path=path),
                    ChannelBindingSettingsStore(db_path=path),
                )
                outreach = OutreachRepositories(
                    OutreachOutboxStore(db_path=path), OutreachDeliveryLogStore(db_path=path)
                )
            else:
                from ..channels.persistence.mysql import (
                    MysqlChannelSessionRepository,
                    MysqlChannelBindingSettingsRepository,
                    MysqlDeliveryReceiptsRepository,
                )
                from ..outreach.persistence.mysql import (
                    MysqlOutreachOutboxRepository,
                    MysqlOutreachDeliveryLogRepository,
                )

                database = require_initialized(self._mysql, "MySQL connection")
                await upgrade_mysql_channels(database)
                await verify_storage_selection(paths, settings, database)
                channels = ChannelRepositories(
                    MysqlChannelSessionRepository(database),
                    MysqlDeliveryReceiptsRepository(database),
                    MysqlChannelBindingSettingsRepository(database),
                )
                outreach = OutreachRepositories(
                    MysqlOutreachOutboxRepository(database),
                    MysqlOutreachDeliveryLogRepository(database),
                )
            events = await compose_event_repository(
                paths, settings.memory_events, settings.mysql, self._mysql
            )
            transfer = (
                SqliteEventStateTransfer(str(paths.l1_memory_db_path))
                if settings.memory_events == "sqlite"
                else MysqlEventStateTransfer(
                    require_initialized(self._mysql, "MySQL connection"),
                    center_id=event_binding_file(paths).read_or_create().center_id,
                )
            )
            self._context.channels.repositories = channels
            self._context.outreach.repositories = outreach
            self._context.memory.event_repository = events
            self._context.memory.event_state_transfer = transfer
            self._chat = await compose_chat_storage(paths, settings, self._mysql)
            self._context.chat.store = self._chat.store
            self._context.chat.reader = self._chat.reader
            self._context.chat.state_transfer = self._chat.state_transfer
        except BaseException:
            await self.shutdown()
            raise

    async def shutdown(self) -> None:
        self._context.channels.repositories = None
        self._context.outreach.repositories = None
        self._context.memory.event_repository = None
        self._context.memory.event_state_transfer = None
        self._context.chat.store = None
        self._context.chat.reader = None
        self._context.chat.state_transfer = None
        try:
            if self._chat is not None:
                await self._chat.close()
        finally:
            self._chat = None
            if self._mysql is not None:
                await self._mysql.close()
                self._mysql = None
