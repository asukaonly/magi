"""Select persistence implementations before channel and outreach applications start."""

from ..channels.ports import ChannelRepositories
from ..channels.persistence.session_mappings import SqliteChannelSessionRepository
from ..channels.receipts_store import DeliveryReceiptsStore
from ..channels.binding_settings_store import ChannelBindingSettingsStore
from ..outreach.ports import OutreachRepositories
from ..outreach.stores import OutreachOutboxStore, OutreachDeliveryLogStore
from ..db.mysql import MysqlDatabase
from ..db.mysql_migrations import upgrade_mysql_channels
from .channel_storage import preflight_storage_selection, verify_storage_selection
from .context import RuntimeBootstrapContext, require_initialized
from .lifecycle import LifecycleModule


class StructuredStorageModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(name="runtime_structured_storage", dependencies=("runtime_configuration",))
        self._context = context
        self._mysql: MysqlDatabase | None = None

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "configuration")
        paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        settings = config.structured_storage
        await preflight_storage_selection(paths, settings)
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

            database = MysqlDatabase(require_initialized(settings.mysql, "MySQL settings"))
            try:
                await upgrade_mysql_channels(database)
                await verify_storage_selection(paths, settings, database)
            except BaseException:
                await database.close()
                raise
            self._mysql = database
            channels = ChannelRepositories(
                MysqlChannelSessionRepository(database),
                MysqlDeliveryReceiptsRepository(database),
                MysqlChannelBindingSettingsRepository(database),
            )
            outreach = OutreachRepositories(
                MysqlOutreachOutboxRepository(database),
                MysqlOutreachDeliveryLogRepository(database),
            )
        self._context.channels.repositories = channels
        self._context.outreach.repositories = outreach

    async def shutdown(self) -> None:
        self._context.channels.repositories = None
        self._context.outreach.repositories = None
        if self._mysql is not None:
            await self._mysql.close()
            self._mysql = None
