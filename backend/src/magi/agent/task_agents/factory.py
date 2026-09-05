"""Factory functions for creating non-chat task agent instances.

The chat-agent factory was relocated to ``magi.chat.task_agent.factory`` in
P2 Task 3 (``ChatTaskAgent`` now lives in the chat layer).
"""

from __future__ import annotations

from typing import Any, Callable

from ...config import AppConfig
from ...agent.runtime.types import TaskAgentType
from ...memory import UnifiedMemoryStore
from . import DefaultTaskAgent, TimelineTaskAgent


def create_default_agent_factory(
    *,
    config: AppConfig,
    unified_memory: UnifiedMemoryStore,
    plugin_manager: Any,
    source_registry: Any,
    source_ingestion_gateway: Any,
    build_timeline_handler: Callable[..., Any],
) -> Callable[[str, str], Any]:
    """Return a factory callable that creates non-chat task agent instances."""

    def _create(agent_type: str, agent_id: str) -> Any:
        if agent_type == TaskAgentType.TIMELINE.value:
            return TimelineTaskAgent(
                agent_id=agent_id,
                timeline_handler=build_timeline_handler(
                    config,
                    unified_memory,
                    source_registry=source_registry,
                    plugin_manager=plugin_manager,
                    ingestion_gateway=source_ingestion_gateway,
                ),
                config=config,
                unified_memory=unified_memory,
            )
        return DefaultTaskAgent(agent_type, agent_id)

    return _create
