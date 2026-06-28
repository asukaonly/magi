"""Runtime dependency assembly for the chat task agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from magi.agent.execution.function_calling import FunctionCallingOrchestrator
from magi.agent.orchestration import get_orchestration_store
from magi.agent.run.ports import LazyAttachmentResolver
from magi.agent.task_agents.common import (
    FactOnlyHandler,
    OrchestrationLaunchHandler,
    OrchestrationUpdateHandler,
)
from magi.agent.task_agents.handlers import ExecutionHandlerRegistry
from magi.agent.task_agents.handlers.direct_handler import DirectLLMHandler
from magi.agent.task_agents.handlers.explore_render import ExploreRenderHandler
from magi.agent.task_agents.handlers.handlers import (
    ChatHandlerDependencies,
    FunctionCallingHandler,
    build_common_handler_dependencies,
)
from magi.agent.task_orchestrator import TaskOrchestrator
from magi.agent.runtime.types import TaskAgentType
from magi.chat import ChatProjector, ChatReadService, ChatStore
from magi.chat.task_agent.context_assembler import ChatContextAssembler
from magi.chat.task_agent.coordinator import ChatExecutionCoordinator
from magi.chat.task_agent.fact_classifier import ChatFactClassifier
from magi.chat.task_agent.interruption_classifier import InterruptionClassifier
from magi.chat.task_agent.planning_service import ChatPlanningService
from magi.chat.task_agent.postprocess_service import ChatPostProcessService
from magi.chat.task_agent.prompt_service import ChatPromptService
from magi.chat.task_agent.rhythm import ResponseRhythmPlanner
from magi.chat.task_agent.run_store import SessionRunStore
from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
from magi.chat.task_agent.transcript_summarizer import ChatTranscriptSummarizer
from magi.context import (
    ContextAssemblyService,
    ContextRetrievalService,
    PromptContextAssembler,
    PromptContextRenderer,
)
from magi.context.user_profile_service import UserProfileService
from magi.runtime_trace import RuntimeTraceStore
from magi.tools.context_decider import ContextDecider
from magi.tools.registry import tool_registry
from magi.utils.runtime import get_runtime_paths


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
    hybrid_retrieval_service: Any | None = None
    history_cache_max_sessions: int = 500
    history_fetch_limit: int = 1000
    skill_runner: Any | None = None
    runtime_trace_store: RuntimeTraceStore | None = None
    chat_store: ChatStore | None = None
    chat_projector: ChatProjector | None = None
    chat_read_service_factory: Callable[[], ChatReadService] | None = None
    background_dispatcher: Any | None = None
    background_launch_service: Any | None = None
    permission_gateway_provider: Callable[[], Any] | None = None
    control_session_store_provider: Callable[[], Any] | None = None
    delivery_dispatcher_resolver: Callable[[], Any] | None = None
    conversation_log_resolver: Callable[[], Any] | None = None
    message_bus: Any | None = None


@dataclass(slots=True)
class ChatTaskAgentRuntimeCallbacks:
    get_event_emitter: Callable[[], Any]
    get_task_agent_manager: Callable[[], Any]
    get_sensor_hub: Callable[[], Any]
    max_fact_memory: int
    drain_deferred_turns: Callable[..., Any]
    deliver_final_response: Callable[..., Any]
    tool_advisory_provider: Callable[..., Any]
    session_workspace_provider: Callable[..., Any]
    persist_turn_supersessions: Callable[..., Any]


@dataclass(slots=True)
class ChatTaskAgentRuntimeParts:
    chat_read_service_factory: Callable[[], ChatReadService]
    context_decider: ContextDecider
    prompt_context_assembler: PromptContextAssembler
    prompt_context_renderer: PromptContextRenderer
    chat_read_service: ChatReadService
    attachment_resolver: LazyAttachmentResolver
    context_retrieval_service: ContextRetrievalService
    context_service: ContextAssemblyService
    context_assembler: ChatContextAssembler
    fact_classifier: ChatFactClassifier
    prompt_service: ChatPromptService
    interruption_classifier: InterruptionClassifier
    session_run_coordinator: SessionRunCoordinator
    planning_service: ChatPlanningService
    orchestration_store: Any
    task_orchestrator: TaskOrchestrator
    transcript_summarizer: ChatTranscriptSummarizer
    postprocess_service: ChatPostProcessService
    function_calling_orchestrator: FunctionCallingOrchestrator
    handler_registry: ExecutionHandlerRegistry
    coordinator: ChatExecutionCoordinator


def build_chat_task_agent_runtime_parts(
    config: ChatTaskAgentRuntimeConfig,
    callbacks: ChatTaskAgentRuntimeCallbacks,
) -> ChatTaskAgentRuntimeParts:
    chat_read_service_factory = (
        config.chat_read_service_factory or default_chat_read_service_factory
    )
    delivery_dispatcher_resolver = config.delivery_dispatcher_resolver or (lambda: None)
    conversation_log_resolver = config.conversation_log_resolver or (lambda: None)
    delivery_dispatcher = delivery_dispatcher_resolver()
    conversation_log = conversation_log_resolver()

    context_decider = ContextDecider(
        tool_registry=tool_registry,
        llm_adapter=config.llm_adapter,
        llm_pool=config.llm_pool,
    )
    prompt_context_assembler = PromptContextAssembler(
        user_profile_service=UserProfileService(unified_memory=config.unified_memory),
    )
    prompt_context_renderer = PromptContextRenderer()
    chat_read_service = chat_read_service_factory()
    attachment_resolver = LazyAttachmentResolver(chat_read_service_factory)
    context_retrieval_service = ContextRetrievalService(
        unified_memory=config.unified_memory,
        retrieval_service=config.hybrid_retrieval_service,
    )
    context_service = ContextAssemblyService(
        agent_id=config.agent_id,
        agent_type=TaskAgentType.CHAT.value,
        prompt_context_assembler=prompt_context_assembler,
        prompt_context_renderer=prompt_context_renderer,
        retrieval_memory_provider=context_retrieval_service.build_retrieved_memory_payload,
        memory=config.memory,
        session_workspace_provider=callbacks.session_workspace_provider,
    )

    runtime_paths = get_runtime_paths()
    context_assembler = ChatContextAssembler(
        l1_db_path=runtime_paths.l1_memory_db_path,
        history_cache_max_sessions=config.history_cache_max_sessions,
        history_fetch_limit=config.history_fetch_limit,
        chat_store=config.chat_store,
        chat_read_service_factory=chat_read_service_factory,
        scenario_llm_pool=config.llm_pool,
        llm_adapter=config.llm_adapter,
    )
    fact_classifier = ChatFactClassifier()
    prompt_service = ChatPromptService(
        llm_adapter=config.llm_adapter,
        llm_pool=config.llm_pool,
    )
    interruption_classifier = InterruptionClassifier(
        llm_adapter=config.llm_adapter,
        llm_pool=config.llm_pool,
    )
    session_run_coordinator = SessionRunCoordinator(
        run_store=SessionRunStore(
            l0_store=(
                config.unified_memory.l0 if config.unified_memory is not None else None
            ),
        ),
        interruption_classifier=interruption_classifier,
        delivery_dispatcher=delivery_dispatcher,
        conversation_log=conversation_log,
    )
    planning_service = ChatPlanningService(
        agent_id=config.agent_id,
        runtime_key=config.runtime_key,
        context_service=context_service,
        prompt_service=prompt_service,
        context_assembler=context_assembler,
        tool_registry=tool_registry,
        parent_task_agent_type=TaskAgentType.CHAT.value,
    )
    orchestration_store = get_orchestration_store()
    task_orchestrator = TaskOrchestrator(
        runtime_key=config.runtime_key,
        tool_registry=tool_registry,
        plan_subtasks=planning_service.generate_subtask_plan,
        aggregate_orchestration=planning_service.aggregate_orchestration,
        register_user_message=context_assembler.append_user_message,
        parent_task_agent_type=TaskAgentType.CHAT.value,
        session_workspace_provider=callbacks.session_workspace_provider,
        control_session_store_provider=config.control_session_store_provider,
    )
    try:
        from magi.runtime_trace.chat_trace.read_service import ChatTraceReadService

        trace_read_service = ChatTraceReadService()
    except Exception:
        trace_read_service = None
    transcript_summarizer = ChatTranscriptSummarizer(
        chat_store=config.chat_store,
        scenario_llm_pool=config.llm_pool,
        llm_adapter=config.llm_adapter,
    )
    postprocess_service = ChatPostProcessService(
        agent_id=config.agent_id,
        context_assembler=context_assembler,
        get_event_emitter=callbacks.get_event_emitter,
        get_task_agent_manager=callbacks.get_task_agent_manager,
        get_sensor_hub=callbacks.get_sensor_hub,
        memory=config.memory,
        unified_memory=config.unified_memory,
        max_fact_memory=callbacks.max_fact_memory,
        trace_read_service=trace_read_service,
        runtime_trace_store=config.runtime_trace_store,
        chat_store=config.chat_store,
        chat_projector=config.chat_projector,
        chat_read_service_factory=chat_read_service_factory,
        complete_session_run=lambda session_id, run_id, revision: session_run_coordinator.complete_run(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
        ),
        resolve_session_run_status=lambda session_id, run_id, revision: session_run_coordinator.get_run_status(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
        ),
        drain_deferred_turns=callbacks.drain_deferred_turns,
        response_rhythm_planner=ResponseRhythmPlanner(),
        transcript_summarizer=transcript_summarizer,
        event_bus=config.message_bus,
        deliver_final_response=(
            callbacks.deliver_final_response
            if delivery_dispatcher is not None
            else None
        ),
    )
    function_calling_orchestrator = FunctionCallingOrchestrator(
        llm_adapter=config.llm_adapter,
        llm_pool=config.llm_pool,
        tool_registry=tool_registry,
        skill_runner=config.skill_runner,
        tool_result_callback=postprocess_service.record_tool_interaction,
        loop_event_callback=postprocess_service.record_tool_loop_fact,
        runtime_trace_store=config.runtime_trace_store,
        scenario_llm_pool=config.llm_pool,
        permission_gateway_provider=config.permission_gateway_provider,
        attachment_resolver=attachment_resolver,
    )
    handler_deps = ChatHandlerDependencies(
        context_service=context_service,
        prompt_service=prompt_service,
        planning_service=planning_service,
        function_calling_orchestrator=function_calling_orchestrator,
        task_orchestrator=task_orchestrator,
        context_assembler=context_assembler,
        agent_id=config.agent_id,
        get_task_agent_manager=callbacks.get_task_agent_manager,
        attachment_resolver=attachment_resolver,
        session_run_coordinator=session_run_coordinator,
        background_dispatcher=config.background_dispatcher,
        background_launch_service=config.background_launch_service,
        persist_turn_supersessions=callbacks.persist_turn_supersessions,
    )
    handler_registry = ExecutionHandlerRegistry()
    common_handler_deps = build_common_handler_dependencies(handler_deps)
    for handler in (
        FactOnlyHandler(common_handler_deps),
        DirectLLMHandler(handler_deps),
        FunctionCallingHandler(handler_deps),
        OrchestrationLaunchHandler(common_handler_deps),
        OrchestrationUpdateHandler(common_handler_deps),
        ExploreRenderHandler(handler_deps),
    ):
        handler_registry.register(handler)
    coordinator = ChatExecutionCoordinator(
        context_decider=context_decider,
        fact_classifier=fact_classifier,
        handler_registry=handler_registry,
        intent_trace_callback=postprocess_service.record_intent_resolution,
        tool_advisory_provider=callbacks.tool_advisory_provider,
        tool_selection_trace_callback=postprocess_service.record_tool_selection,
        delivery_dispatcher=delivery_dispatcher,
        conversation_log=conversation_log,
        attachment_resolver=attachment_resolver,
    )
    handler_deps.coordinator = coordinator

    return ChatTaskAgentRuntimeParts(
        chat_read_service_factory=chat_read_service_factory,
        context_decider=context_decider,
        prompt_context_assembler=prompt_context_assembler,
        prompt_context_renderer=prompt_context_renderer,
        chat_read_service=chat_read_service,
        attachment_resolver=attachment_resolver,
        context_retrieval_service=context_retrieval_service,
        context_service=context_service,
        context_assembler=context_assembler,
        fact_classifier=fact_classifier,
        prompt_service=prompt_service,
        interruption_classifier=interruption_classifier,
        session_run_coordinator=session_run_coordinator,
        planning_service=planning_service,
        orchestration_store=orchestration_store,
        task_orchestrator=task_orchestrator,
        transcript_summarizer=transcript_summarizer,
        postprocess_service=postprocess_service,
        function_calling_orchestrator=function_calling_orchestrator,
        handler_registry=handler_registry,
        coordinator=coordinator,
    )
