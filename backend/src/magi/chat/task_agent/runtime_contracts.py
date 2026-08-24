"""Runtime assembly contracts for the chat task agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from magi.agent.execution.attachment_resolver import LazyAttachmentResolver
    from magi.agent.task_agents.handlers import ExecutionHandlerRegistry
    from magi.agent.execution.function_calling import FunctionCallingOrchestrator
    from magi.chat import ChatReadService, ChatStore
    from magi.chat.task_agent.context_assembler import ChatContextAssembler
    from magi.chat.task_agent.coordinator import ChatExecutionCoordinator
    from magi.chat.task_agent.fact_classifier import ChatFactClassifier
    from magi.chat.task_agent.postprocess_service import ChatPostProcessService
    from magi.chat.task_agent.prompt_service import ChatPromptService
    from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
    from magi.chat.task_agent.transcript_summarizer import ChatTranscriptSummarizer
    from magi.context import (
        ContextAssemblyService,
        ContextRetrievalService,
        PromptContextAssembler,
        PromptContextRenderer,
    )
    from magi.runtime_trace import RuntimeTraceStore


def default_chat_read_service_factory() -> ChatReadService:
    from magi.chat import get_chat_read_service

    return get_chat_read_service()


@dataclass(slots=True)
class ChatTaskAgentRuntimeConfig:
    agent_id: str
    runtime_key: str
    llm_adapter: Any | None = None
    llm_pool: Any | None = None
    memory: Any | None = None
    unified_memory: Any | None = None
    post_turn_understanding_service: Any | None = None
    hybrid_retrieval_service: Any | None = None
    history_cache_max_sessions: int = 500
    skill_runner: Any | None = None
    runtime_trace_store: RuntimeTraceStore | None = None
    chat_store: ChatStore | None = None
    chat_read_service_factory: Callable[[], ChatReadService] | None = None
    background_launch_service: Any | None = None
    permission_gateway_provider: Callable[[], Any] | None = None
    delivery_dispatcher_resolver: Callable[[], Any] | None = None
    conversation_log_resolver: Callable[[], Any] | None = None
    message_bus: Any | None = None


@dataclass(slots=True)
class ChatTaskAgentRuntimeCallbacks:
    get_event_emitter: Callable[[], Any]
    get_task_agent_manager: Callable[[], Any]
    get_sensor_hub: Callable[[], Any]
    max_fact_memory: int
    release_pending_inputs: Callable[..., Any]
    deliver_final_response: Callable[..., Any]
    tool_advisory_provider: Callable[..., Any]
    session_workspace_provider: Callable[..., Any]


@dataclass(slots=True)
class ChatTaskAgentRuntimeParts:
    chat_read_service_factory: Callable[[], ChatReadService]
    prompt_context_assembler: PromptContextAssembler
    prompt_context_renderer: PromptContextRenderer
    chat_read_service: ChatReadService
    attachment_resolver: LazyAttachmentResolver
    context_retrieval_service: ContextRetrievalService
    context_service: ContextAssemblyService
    context_assembler: ChatContextAssembler
    fact_classifier: ChatFactClassifier
    prompt_service: ChatPromptService
    session_run_coordinator: SessionRunCoordinator
    transcript_summarizer: ChatTranscriptSummarizer
    postprocess_service: ChatPostProcessService
    function_calling_orchestrator: FunctionCallingOrchestrator
    handler_registry: ExecutionHandlerRegistry
    coordinator: ChatExecutionCoordinator
