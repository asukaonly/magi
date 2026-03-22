"""Factory functions for creating task agent instances."""

from __future__ import annotations

from typing import Any, Callable

from ...config import AppConfig
from ...agent.runtime.types import TaskAgentType
from ...chat import ChatProjector, ChatStore
from ...memory import UnifiedMemoryStore
from ...memory.hybrid_retrieval import HybridRetrievalService
from ...memory.integration import MemoryIntegrationModule
from ...runtime_trace import RuntimeTraceStore
from ...timeline.handler import build_timeline_handler
from . import ChatTaskAgent, DefaultTaskAgent, ExploreTaskAgent, TimelineTaskAgent


def create_chat_agent_factory(
    *,
    llm_adapter: Any,
    llm_pool: Any,
    memory: Any,
    other_memory: Any,
    unified_memory: UnifiedMemoryStore,
    hybrid_retrieval_service: HybridRetrievalService,
    memory_integration: MemoryIntegrationModule,
    scenario_prompts_store: Any,
    skill_runner: Any,
    runtime_trace_store: RuntimeTraceStore | None,
    chat_store: ChatStore | None,
    chat_projector: ChatProjector | None,
    config: AppConfig,
) -> Callable[[str], ChatTaskAgent]:
    """Return a factory callable that creates ChatTaskAgent instances."""

    def _create(agent_id: str) -> ChatTaskAgent:
        return ChatTaskAgent(
            agent_id=agent_id,
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
            memory=memory,
            other_memory=other_memory,
            unified_memory=unified_memory,
            hybrid_retrieval_service=hybrid_retrieval_service,
            memory_integration=memory_integration,
            history_cache_max_sessions=config.agent.runtime.chat_history_cache_max_sessions,
            history_fetch_limit=config.agent.runtime.chat_history_fetch_limit,
            scenario_prompts_store=scenario_prompts_store,
            skill_runner=skill_runner,
            runtime_trace_store=runtime_trace_store,
            chat_store=chat_store,
            chat_projector=chat_projector,
        )

    return _create


def create_default_agent_factory(
    *,
    llm_adapter: Any,
    llm_pool: Any,
    config: AppConfig,
    unified_memory: UnifiedMemoryStore,
    plugin_manager: Any,
    sensor_registry: Any,
) -> Callable[[str, str], Any]:
    """Return a factory callable that creates non-chat task agent instances."""

    def _create(agent_type: str, agent_id: str) -> Any:
        if agent_type == TaskAgentType.EXPLORE.value:
            return ExploreTaskAgent(agent_id=agent_id, llm_adapter=llm_adapter, llm_pool=llm_pool)
        if agent_type == TaskAgentType.TIMELINE.value:
            return TimelineTaskAgent(
                agent_id=agent_id,
                timeline_handler=build_timeline_handler(
                    config,
                    unified_memory,
                    sensor_registry=sensor_registry,
                    plugin_manager=plugin_manager,
                ),
                config=config,
                unified_memory=unified_memory,
            )
        return DefaultTaskAgent(agent_type, agent_id)

    return _create
