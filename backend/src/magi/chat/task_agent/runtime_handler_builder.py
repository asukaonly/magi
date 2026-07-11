"""Handler and coordinator assembly for the chat task agent."""

from __future__ import annotations

from dataclasses import dataclass

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
from magi.chat.task_agent.coordinator import ChatExecutionCoordinator
from magi.chat.task_agent.run_placement_service import ChatRunPlacementService

from .runtime_context_builder import ChatContextRuntimeParts
from .runtime_contracts import (
    ChatTaskAgentRuntimeCallbacks,
    ChatTaskAgentRuntimeConfig,
)
from .runtime_execution_builder import ChatExecutionRuntimeParts


@dataclass(slots=True)
class ChatHandlerRuntimeParts:
    handler_registry: ExecutionHandlerRegistry
    coordinator: ChatExecutionCoordinator


def build_chat_handler_runtime_parts(
    config: ChatTaskAgentRuntimeConfig,
    callbacks: ChatTaskAgentRuntimeCallbacks,
    context_parts: ChatContextRuntimeParts,
    execution_parts: ChatExecutionRuntimeParts,
) -> ChatHandlerRuntimeParts:
    handler_deps = _build_handler_dependencies(
        config,
        callbacks,
        context_parts=context_parts,
        execution_parts=execution_parts,
    )
    handler_registry = _build_handler_registry(handler_deps)
    coordinator = _build_coordinator(
        config,
        callbacks,
        context_parts=context_parts,
        execution_parts=execution_parts,
        handler_registry=handler_registry,
    )
    handler_deps.coordinator = coordinator
    return ChatHandlerRuntimeParts(
        handler_registry=handler_registry,
        coordinator=coordinator,
    )


def _build_handler_dependencies(
    config: ChatTaskAgentRuntimeConfig,
    callbacks: ChatTaskAgentRuntimeCallbacks,
    *,
    context_parts: ChatContextRuntimeParts,
    execution_parts: ChatExecutionRuntimeParts,
) -> ChatHandlerDependencies:
    return ChatHandlerDependencies(
        context_service=context_parts.context_service,
        prompt_service=context_parts.prompt_service,
        planning_service=execution_parts.planning_service,
        function_calling_orchestrator=execution_parts.function_calling_orchestrator,
        task_orchestrator=execution_parts.task_orchestrator,
        context_assembler=context_parts.context_assembler,
        agent_id=config.agent_id,
        get_task_agent_manager=callbacks.get_task_agent_manager,
        model_context_provider=context_parts.model_context_provider,
        attachment_resolver=context_parts.attachment_resolver,
        session_run_coordinator=execution_parts.session_run_coordinator,
        background_launch_service=config.background_launch_service,
        persist_turn_supersessions=callbacks.persist_turn_supersessions,
    )


def _build_handler_registry(
    handler_deps: ChatHandlerDependencies,
) -> ExecutionHandlerRegistry:
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
    return handler_registry


def _build_coordinator(
    config: ChatTaskAgentRuntimeConfig,
    callbacks: ChatTaskAgentRuntimeCallbacks,
    *,
    context_parts: ChatContextRuntimeParts,
    execution_parts: ChatExecutionRuntimeParts,
    handler_registry: ExecutionHandlerRegistry,
) -> ChatExecutionCoordinator:
    return ChatExecutionCoordinator(
        context_decider=context_parts.context_decider,
        fact_classifier=context_parts.fact_classifier,
        handler_registry=handler_registry,
        intent_trace_callback=execution_parts.postprocess_service.record_intent_resolution,
        tool_advisory_provider=callbacks.tool_advisory_provider,
        tool_selection_trace_callback=execution_parts.postprocess_service.record_tool_selection,
        delivery_dispatcher=execution_parts.delivery_dispatcher,
        conversation_log=execution_parts.conversation_log,
        attachment_resolver=context_parts.attachment_resolver,
        run_placement_service=ChatRunPlacementService(
            background_dispatcher=config.background_dispatcher,
            background_launch_service=config.background_launch_service,
            session_run_coordinator=execution_parts.session_run_coordinator,
        ),
    )
