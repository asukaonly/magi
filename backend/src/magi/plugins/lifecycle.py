"""L4 Plugin Registration Layer lifecycle module."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from .manager import build_plugin_runtime
from .user_content_clear import PluginUserContentClearCoordinator
from .user_content_clear_checkpoint import PluginUserContentClearCheckpointStore

logger = get_logger(__name__)


class PluginSystemModule(LifecycleModule):
    """Initialize plugin manager and plugin metadata (L4)."""

    def __init__(
        self,
        context: RuntimeBootstrapContext,
        *,
        tool_registry: Any,
        request_source_schedule_refresh: Callable[[], None],
    ):
        super().__init__(
            name="runtime_plugin_system",
            dependencies=("runtime_configuration", "runtime_command_queue"),
        )
        self._context = context
        self._tool_registry = tool_registry
        self._request_source_schedule_refresh = request_source_schedule_refresh
        self._runtime_loop: asyncio.AbstractEventLoop | None = None

    async def init(self) -> None:
        runtime_loop = asyncio.get_running_loop()
        self._runtime_loop = runtime_loop

        def request_source_schedule_refresh() -> None:
            if self._runtime_loop is not runtime_loop or runtime_loop.is_closed():
                return
            try:
                runtime_loop.call_soon_threadsafe(
                    self._run_source_schedule_refresh,
                    runtime_loop,
                )
            except RuntimeError:
                # The loop can close between the state check and scheduling.
                return

        runtime_command_queue = require_initialized(
            self._context.runtime_commands.runtime_command_queue,
            "runtime command queue",
        )
        transaction_state = await runtime_command_queue.read_full_user_content_clear_state()
        full_clear_recovery_pending = transaction_state.status == "pending"
        self._context.runtime_commands.full_clear_recovery_pending = full_clear_recovery_pending

        from ..awareness.source_store import SourceStore
        from ..skills.indexer import SkillIndexer
        from ..skills.loader import SkillLoader
        from ..hooks.registry import HookRegistry
        from .connection_content import ConnectionContentCoordinator
        from .operations import PluginOperationRegistry
        from .operation_authorization import InstalledOperationAuthorizer
        from .providers import PluginProviderRegistry
        from .skills import PluginSkillRegistry
        from .operation_execution import run_plugin_lifecycle_operation
        from .process_broker import bind_source_services
        from .process_runtime import ProcessPluginProxy
        from magi_plugin_sdk.runtime import CapabilityGrant
        from ..config import get_config

        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        source_store = SourceStore(runtime_paths.runtime_dir / "plugin_sources.db")
        await source_store.initialize()
        content = ConnectionContentCoordinator(source_store)

        async def enqueue_source_change(payload: dict[str, Any]) -> None:
            async def enqueue() -> None:
                contributor = require_initialized(
                    self._context.agent_runtime.source_scheduler_contrib,
                    "source scheduler contributor",
                )
                await contributor.queue_source_change(payload)

            if asyncio.get_running_loop() is runtime_loop:
                await enqueue()
            else:
                await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(enqueue(), runtime_loop))

        def configure_instance(manifest: Any, instance: Any) -> None:
            if not isinstance(instance, ProcessPluginProxy):
                return
            connection_id = instance.connection_id
            source_types = frozenset(
                str(spec.metadata.get("source_type") or source.source_type)
                for _source_id, source, spec in instance.get_sources()
            )
            for capability, scopes in (
                ("source.emit", sorted(source_types)),
                ("resources.create", [connection_id]),
                ("resources.read", [connection_id]),
            ):
                if scopes:
                    instance.broker.grant(CapabilityGrant(
                        grant_id=f"{connection_id}:{capability}", connection_id=connection_id,
                        capability=capability, scopes=scopes,
                    ))
            bind_source_services(
                instance.broker, get_connection=get_connection, source_store=source_store,
                emit_change=enqueue_source_change, source_types=source_types,
            )
        indexer = SkillIndexer()
        loader = SkillLoader(indexer)
        self._context.skills.skill_indexer = indexer
        self._context.skills.skill_loader = loader
        skills = PluginSkillRegistry(self._tool_registry, indexer, loader)
        if self._context.hooks.registry is None:
            self._context.hooks.registry = HookRegistry()

        def get_connection(connection_id: str):
            return bindings.plugin_manager.connection_store.get(connection_id)

        def operation_authorizer() -> InstalledOperationAuthorizer:
            manager = bindings.plugin_manager
            return InstalledOperationAuthorizer(
                get_package=manager.get_package, connection_store=manager.connection_store,
                config_provider=get_config,
            )

        class ConnectionAuthorizer:
            """Resolve live manager authority after bootstrap construction."""

            def __call__(self, *args: Any) -> bool:
                return operation_authorizer()(*args)

            def authorize_setup(self, *args: Any) -> bool:
                return operation_authorizer().authorize_setup(*args)

        operations = PluginOperationRegistry(
            self._tool_registry, get_connection=get_connection, authorize=ConnectionAuthorizer(),
            validate_resource=source_store.validate_operation_resource,
        )
        providers = PluginProviderRegistry(get_connection=get_connection)

        bindings = build_plugin_runtime(
            tool_registry=self._tool_registry,
            request_source_schedule_refresh=request_source_schedule_refresh,
            activate_enabled=False,
            skill_registrar=skills,
            operation_registrar=operations,
            provider_registrar=providers,
            content_clearer=content.clear,
            connection_disconnector=content.disconnect,
            configure_instance=configure_instance,
            hook_registry_provider=lambda: self._context.hooks.registry,
        )
        self._context.plugins.plugin_manager = bindings.plugin_manager
        self._context.plugins.plugin_projection_service = bindings.plugin_projection_service
        self._context.plugins.source_registry = bindings.source_registry
        self._context.plugins.history_importer_registry = bindings.history_importer_registry
        self._context.plugins.source_store = source_store
        self._context.plugins.operation_registry = operations
        self._context.plugins.provider_registry = providers
        if not full_clear_recovery_pending:
            await run_plugin_lifecycle_operation(
                lambda: bindings.plugin_manager.scan(persist_discovery=True),
            )
            await run_plugin_lifecycle_operation(bindings.plugin_manager.activate_enabled_plugins)
        self._context.plugins.user_content_clear_coordinator = PluginUserContentClearCoordinator(
            plugin_manager=bindings.plugin_manager,
            runtime_paths=require_initialized(
                self._context.core.runtime_paths,
                "runtime paths",
            ),
            get_source_sync_executor=lambda: (self._context.agent_runtime.source_sync_executor),
            checkpoint_store=PluginUserContentClearCheckpointStore(
                require_initialized(
                    self._context.core.runtime_paths,
                    "runtime paths",
                ).message_queue_db_path
            ),
            read_current_clear_generation=require_initialized(
                self._context.runtime_commands.runtime_command_queue,
                "runtime command queue",
            ).read_current_clear_generation,
            source_store=source_store,
        )
        pending_plugin_clear = await (
            self._context.plugins.user_content_clear_coordinator
        ).has_pending_generation()
        if pending_plugin_clear and not full_clear_recovery_pending:
            raise RuntimeError("Interrupted full user-content clear has no durable recovery owner")
        if full_clear_recovery_pending:
            logger.warning(
                "Interrupted full user-content clear awaits desktop recovery",
                transaction_id=transaction_state.transaction_id,
            )

    def _run_source_schedule_refresh(
        self,
        runtime_loop: asyncio.AbstractEventLoop,
    ) -> None:
        if self._runtime_loop is not runtime_loop or runtime_loop.is_closed():
            return
        self._request_source_schedule_refresh()

    async def shutdown(self) -> None:
        self._runtime_loop = None
        manager = self._context.plugins.plugin_manager
        if manager is not None:
            await manager.shutdown()
        self._context.plugins.user_content_clear_coordinator = None
        self._context.plugins.plugin_manager = None
        self._context.plugins.plugin_projection_service = None
        self._context.plugins.source_registry = None
        self._context.plugins.history_importer_registry = None
        self._context.plugins.source_store = None
        self._context.plugins.operation_registry = None
        self._context.plugins.provider_registry = None
        self._context.runtime_commands.full_clear_recovery_pending = False
