"""Lifecycle ownership for durable one-shot history imports."""

from __future__ import annotations

from dependency_injector import providers

from ...bootstrap.context import RuntimeBootstrapContext, require_initialized
from ...bootstrap.lifecycle import LifecycleModule
from ...core.container import get_container
from .service import HistoryImportService
from .store import HistoryImportStore


class HistoryImportsModule(LifecycleModule):
    """Build the import store and resume confirmed background work."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_history_imports",
            dependencies=(
                "runtime_database_migrations",
                "runtime_memory",
                "runtime_plugin_system",
                "runtime_l2_consolidation_scheduler",
            ),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = require_initialized(
            self._context.core.runtime_paths,
            "runtime paths",
        )
        memory = require_initialized(
            self._context.memory.unified_memory,
            "unified memory",
        )
        importer_registry = require_initialized(
            self._context.plugins.history_importer_registry,
            "history importer registry",
        )
        store = HistoryImportStore(db_path=str(runtime_paths.memory_db_path))
        from ..l2.consolidation_schedule import request_l2_consolidation

        async def request_consolidation() -> None:
            scheduler = require_initialized(
                self._context.scheduler.scheduler_service, "scheduler service"
            )
            await request_l2_consolidation(scheduler, reason="history_import_completed")

        service = HistoryImportService(
            store=store,
            memory=memory,
            importer_registry=importer_registry,
            consolidation_request=request_consolidation,
        )
        if not self._context.runtime_commands.full_clear_recovery_pending:
            await service.start()

        self._context.history_imports.store = store
        self._context.history_imports.service = service
        get_container().history_import_service.override(providers.Object(service))

    async def shutdown(self) -> None:
        service = self._context.history_imports.service
        if service is not None:
            await service.stop()
        get_container().history_import_service.reset_override()
        self._context.history_imports.store = None
        self._context.history_imports.service = None


__all__ = ["HistoryImportsModule"]
