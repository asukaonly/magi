"""
Dependency injection container for Magi application.

Provides centralized service management using dependency-injector library.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from dependency_injector import containers, providers

if TYPE_CHECKING:
    from ..agent.runtime import AgentRuntime
    from ..runtime_trace.chat_trace.read_service import ChatTraceReadService
    from ..bootstrap.context import RuntimeBootstrapContext
    from ..bootstrap.lifecycle import ModuleLifecycleOrchestrator
    from ..chat import ChatProjector, ChatReadService, ChatStore
    from ..events.backend import MessageBusBackend
    from ..events.runtime_queue import SQLiteRuntimeCommandQueue
    from ..llm.scenario_pool import ScenarioLLMPool
    from ..memory.integration import MemoryIntegrationModule
    from ..memory import UnifiedMemoryStore
    from ..memory.hybrid_retrieval import HybridRetrievalService
    from ..memory.manual_entries import (
        ManualEntryAssetStore,
        ManualEntryStore,
        WeatherFetcher,
    )
    from ..location.store import LocationSampleStore
    from ..scheduler.service import SchedulerService
    from ..plugins import PluginManager, PluginProjectionService, SensorRegistry
    from ..runtime_trace import RuntimeTraceStore
    from ..awareness.scheduler_contrib import SensorSchedulerContrib


def _create_chat_read_service():
    """Factory function for ChatReadService."""
    from ..chat.read_service import ChatReadService
    return ChatReadService()


def _create_chat_attachment_ingestion_service():
    """Factory function for LocalChatAttachmentIngestionService."""
    from ..chat.attachment_ingestion import LocalChatAttachmentIngestionService
    return LocalChatAttachmentIngestionService()


def _create_chat_surface_write_service():
    """Factory function for ChatSurfaceWriteService."""
    from ..chat.surface_writes import ChatSurfaceWriteService
    return ChatSurfaceWriteService()


def _create_chat_forgetting_service():
    """Build the chat deletion coordinator from active runtime bindings."""
    from ..chat.forgetting import get_chat_forgetting_service

    return get_chat_forgetting_service()


def _create_embedding_rebuild_manager():
    """Build the process-wide embedding rebuild manager."""
    from ..memory.embedding.vector_admin import get_embedding_rebuild_manager

    return get_embedding_rebuild_manager()


def _create_chat_trace_read_service():
    """Factory function for ChatTraceReadService."""
    from ..runtime_trace.chat_trace.read_service import ChatTraceReadService
    return ChatTraceReadService()


class Container(containers.DeclarativeContainer):
    """
    Main dependency injection container for Magi.

    Wiring configuration enables automatic injection in FastAPI routes
    and other modules.
    """

    wiring_config = containers.WiringConfiguration(
        modules=[
            "magi.api.routers.messages",
            "magi.api.routers.skills",
        ]
    )

    # Core runtime services — placeholders overridden at bootstrap time.
    # Type annotations (TYPE_CHECKING only) indicate the runtime type.
    message_bus: providers.Singleton[MessageBusBackend] = providers.Singleton(object)
    runtime_command_queue: providers.Singleton[SQLiteRuntimeCommandQueue] = providers.Singleton(object)
    chat_store: providers.Singleton[ChatStore] = providers.Singleton(object)
    chat_projector: providers.Singleton[ChatProjector] = providers.Singleton(object)
    agent_runtime: providers.Singleton[AgentRuntime] = providers.Singleton(object)
    memory_integration: providers.Singleton[MemoryIntegrationModule] = providers.Singleton(object)
    unified_memory: providers.Singleton[UnifiedMemoryStore] = providers.Singleton(object)
    hybrid_retrieval_service: providers.Singleton[HybridRetrievalService] = providers.Singleton(object)
    location_sample_store: providers.Singleton[LocationSampleStore] = providers.Singleton(object)
    manual_entry_store: providers.Singleton[ManualEntryStore] = providers.Singleton(object)
    manual_entry_asset_store: providers.Singleton[ManualEntryAssetStore] = providers.Singleton(object)
    manual_entry_weather_fetcher: providers.Singleton[WeatherFetcher] = providers.Singleton(object)
    history_import_service: providers.Singleton[Any] = providers.Singleton(object)
    scheduler_service: providers.Singleton[SchedulerService] = providers.Singleton(object)
    sensor_scheduler_contrib: providers.Singleton[SensorSchedulerContrib] = providers.Singleton(object)
    scenario_llm_pool: providers.Singleton[ScenarioLLMPool] = providers.Singleton(object)
    plugin_manager: providers.Singleton[PluginManager] = providers.Singleton(object)
    plugin_projection_service: providers.Singleton[PluginProjectionService] = providers.Singleton(object)
    sensor_registry: providers.Singleton[SensorRegistry] = providers.Singleton(object)
    runtime_trace_store: providers.Singleton[RuntimeTraceStore] = providers.Singleton(object)
    skill_indexer: providers.Singleton[Any] = providers.Singleton(object)
    skill_loader: providers.Singleton[Any] = providers.Singleton(object)
    skill_runner: providers.Singleton[Any] = providers.Singleton(object)
    runtime_orchestrator: providers.Singleton[ModuleLifecycleOrchestrator] = providers.Singleton(object)
    runtime_bootstrap_context: providers.Singleton[RuntimeBootstrapContext] = providers.Singleton(object)
    background_task_manager: providers.Singleton[Any] = providers.Singleton(object)
    chat_portrait_service: providers.Singleton[Any] = providers.Singleton(object)
    chat_message_notifier: providers.Singleton[Any] = providers.Singleton(object)
    user_message_dispatcher: providers.Singleton[Any] = providers.Singleton(object)
    control_session_store: providers.Singleton[Any] = providers.Singleton(object)
    control_settings_manager: providers.Singleton[Any] = providers.Singleton(object)
    permission_gateway: providers.Singleton[Any] = providers.Singleton(object)
    permission_rule_store: providers.Singleton[Any] = providers.Singleton(object)
    control_interaction_broker: providers.Singleton[Any] = providers.Singleton(object)
    pending_permission_registry: providers.Singleton[Any] = providers.Singleton(object)
    hook_gateway: providers.Singleton[Any] = providers.Singleton(object)
    hook_registry: providers.Singleton[Any] = providers.Singleton(object)

    # Container-owned read services and lightweight service providers.
    chat_read_service: providers.Singleton[ChatReadService] = providers.Singleton(
        _create_chat_read_service
    )
    chat_attachment_ingestion_service: providers.Singleton[Any] = providers.Singleton(
        _create_chat_attachment_ingestion_service
    )
    chat_surface_write_service: providers.Singleton[Any] = providers.Singleton(
        _create_chat_surface_write_service
    )
    chat_forgetting_service: providers.Factory[Any] = providers.Factory(
        _create_chat_forgetting_service
    )
    embedding_rebuild_manager: providers.Singleton[Any] = providers.Singleton(
        _create_embedding_rebuild_manager
    )
    chat_trace_read_service: providers.Singleton[ChatTraceReadService] = providers.Singleton(
        _create_chat_trace_read_service
    )


# Global container instance
_container: Optional[Container] = None


def get_container() -> Container:
    """Get the global container instance."""
    global _container
    if _container is None:
        _container = Container()
    return _container


def init_container() -> Container:
    """Initialize and return the global container."""
    global _container
    _container = Container()
    return _container


def wire_container() -> Container:
    """Initialize, wire, and return the global container."""
    container = init_container()
    container.wire(modules=Container.wiring_config.modules)
    return container
