"""
Dependency injection container for Magi application.

Provides centralized service management using dependency-injector library.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from dependency_injector import containers, providers

if TYPE_CHECKING:
    from ..agent.runtime import AgentRuntime
    from ..events.sqlite_backend import SQLiteMessageBackend
    from ..memory.integration import MemoryIntegrationModule
    from ..awareness.sensors import UserMessageSensor
    from ..api.services import ChatReadService


def _create_chat_read_service():
    """Factory function for ChatReadService."""
    from ..api.services.chat_read_service import ChatReadService
    return ChatReadService()


def _create_user_message_sensor():
    """Factory function for UserMessageSensor."""
    from ..awareness.sensors import UserMessageSensor
    return UserMessageSensor()


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
            "magi.api.websocket.handlers",
            "magi.backend_app",
        ]
    )

    # Core runtime services (initialized in bootstrap)
    # These use Configuration providers that are overridden at runtime
    message_bus = providers.Singleton(object)  # Placeholder, overridden in bootstrap
    agent_runtime = providers.Singleton(object)  # Placeholder, overridden in bootstrap
    memory_integration = providers.Singleton(object)  # Placeholder, overridden in bootstrap
    unified_memory = providers.Singleton(object)  # Placeholder, overridden in bootstrap
    scheduler_service = providers.Singleton(object)  # Placeholder, overridden in bootstrap
    scenario_llm_pool = providers.Singleton(object)  # Placeholder, overridden in bootstrap

    # Factory providers for per-request instances
    chat_read_service = providers.Factory(_create_chat_read_service)
    user_message_sensor = providers.Singleton(_create_user_message_sensor)


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
