"""Factory functions for creating non-chat task agent instances.

The chat-agent factory was relocated to ``magi.chat.task_agent.factory`` in
P2 Task 3 (``ChatTaskAgent`` now lives in the chat layer).
"""

from __future__ import annotations

from typing import Any, Callable

from ...config import AppConfig
from ...agent.runtime.types import TaskAgentType
from ...memory import UnifiedMemoryStore
from . import DefaultTaskAgent, ExploreTaskAgent, TimelineTaskAgent


def create_default_agent_factory(
    *,
    llm_adapter: Any,
    llm_pool: Any,
    config: AppConfig,
    unified_memory: UnifiedMemoryStore,
    plugin_manager: Any,
    sensor_registry: Any,
    sensor_ingestion_gateway: Any,
    build_timeline_handler: Callable[..., Any],
    control_session_store_provider: Callable[[], Any] | None = None,
    chat_store: Any | None = None,
) -> Callable[[str, str], Any]:
    """Return a factory callable that creates non-chat task agent instances."""

    def _create(agent_type: str, agent_id: str) -> Any:
        if agent_type == TaskAgentType.EXPLORE.value:
            return ExploreTaskAgent(
                agent_id=agent_id,
                llm_adapter=llm_adapter,
                llm_pool=llm_pool,
                control_session_store_provider=control_session_store_provider,
                chat_store=chat_store,
            )
        if agent_type == TaskAgentType.TIMELINE.value:
            return TimelineTaskAgent(
                agent_id=agent_id,
                timeline_handler=build_timeline_handler(
                    config,
                    unified_memory,
                    sensor_registry=sensor_registry,
                    plugin_manager=plugin_manager,
                    ingestion_gateway=sensor_ingestion_gateway,
                ),
                config=config,
                unified_memory=unified_memory,
            )
        return DefaultTaskAgent(agent_type, agent_id)

    return _create
