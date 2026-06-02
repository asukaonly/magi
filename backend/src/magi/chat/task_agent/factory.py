"""Factory function for creating ChatTaskAgent instances."""

from __future__ import annotations

from typing import Any, Callable

from magi.config import AppConfig
from magi.chat import ChatProjector, ChatStore
from magi.memory import UnifiedMemoryStore
from magi.memory.hybrid_retrieval import HybridRetrievalService
from magi.memory.integration import MemoryIntegrationModule
from magi.runtime_trace import RuntimeTraceStore

from .chat_task_agent import ChatTaskAgent


def create_chat_agent_factory(
    *,
    llm_adapter: Any,
    llm_pool: Any,
    memory: Any,
    unified_memory: UnifiedMemoryStore,
    hybrid_retrieval_service: HybridRetrievalService,
    memory_integration: MemoryIntegrationModule,
    skill_runner: Any,
    runtime_trace_store: RuntimeTraceStore | None,
    chat_store: ChatStore | None,
    chat_projector: ChatProjector | None,
    chat_read_service_factory: Callable[[], Any],
    config: AppConfig,
    background_dispatcher: Any | None = None,
    background_launch_service: Any | None = None,
    permission_gateway_provider: Callable[[], Any] | None = None,
    control_session_store_provider: Callable[[], Any] | None = None,
) -> Callable[[str], ChatTaskAgent]:
    """Return a factory callable that creates ChatTaskAgent instances."""

    def _create(agent_id: str) -> ChatTaskAgent:
        return ChatTaskAgent(
            agent_id=agent_id,
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
            memory=memory,
            unified_memory=unified_memory,
            hybrid_retrieval_service=hybrid_retrieval_service,
            memory_integration=memory_integration,
            history_cache_max_sessions=config.agent.runtime.chat_history_cache_max_sessions,
            history_fetch_limit=config.agent.runtime.chat_history_fetch_limit,
            skill_runner=skill_runner,
            runtime_trace_store=runtime_trace_store,
            chat_store=chat_store,
            chat_projector=chat_projector,
            chat_read_service_factory=chat_read_service_factory,
            background_dispatcher=background_dispatcher,
            background_launch_service=background_launch_service,
            permission_gateway_provider=permission_gateway_provider,
            control_session_store_provider=control_session_store_provider,
        )

    return _create
