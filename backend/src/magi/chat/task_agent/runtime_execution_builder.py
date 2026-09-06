"""Execution runtime assembly for the chat task agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from magi.agent.execution.function_calling import FunctionCallingOrchestrator
from magi.chat.task_agent.postprocess_service import ChatPostProcessService
from magi.agent.response_rhythm import ResponseRhythmPlanner
from magi.chat.task_agent.run_store import SessionRunStore
from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
from magi.config.models import LLMScenario
from magi.tools.registry import tool_registry

from .runtime_context_builder import ChatContextRuntimeParts
from .runtime_contracts import (
    ChatTaskAgentRuntimeCallbacks,
    ChatTaskAgentRuntimeConfig,
)


@dataclass(slots=True)
class ChatExecutionRuntimeParts:
    delivery_dispatcher: Any
    conversation_log: Any
    session_run_coordinator: SessionRunCoordinator
    postprocess_service: ChatPostProcessService
    function_calling_orchestrator: FunctionCallingOrchestrator


def build_chat_execution_runtime_parts(
    config: ChatTaskAgentRuntimeConfig,
    callbacks: ChatTaskAgentRuntimeCallbacks,
    context_parts: ChatContextRuntimeParts,
) -> ChatExecutionRuntimeParts:
    delivery_dispatcher = _resolve_optional_runtime_dependency(
        config.delivery_dispatcher_resolver,
    )
    conversation_log = _resolve_optional_runtime_dependency(
        config.conversation_log_resolver,
    )
    session_run_coordinator = _build_session_run_coordinator(
        config,
        context_parts=context_parts,
        delivery_dispatcher=delivery_dispatcher,
        conversation_log=conversation_log,
    )
    postprocess_service = _build_postprocess_service(
        config,
        callbacks,
        context_parts=context_parts,
        session_run_coordinator=session_run_coordinator,
        delivery_dispatcher=delivery_dispatcher,
    )

    return ChatExecutionRuntimeParts(
        delivery_dispatcher=delivery_dispatcher,
        conversation_log=conversation_log,
        session_run_coordinator=session_run_coordinator,
        postprocess_service=postprocess_service,
        function_calling_orchestrator=_build_function_calling_orchestrator(
            config,
            context_parts=context_parts,
            postprocess_service=postprocess_service,
        ),
    )


def _resolve_optional_runtime_dependency(resolver: Any | None) -> Any:
    if resolver is None:
        return None
    return resolver()


def _build_session_run_coordinator(
    config: ChatTaskAgentRuntimeConfig,
    *,
    context_parts: ChatContextRuntimeParts,
    delivery_dispatcher: Any,
    conversation_log: Any,
) -> SessionRunCoordinator:
    return SessionRunCoordinator(
        run_store=SessionRunStore(
            workbench_store=(
                config.unified_memory.l0 if config.unified_memory is not None else None
            ),
        ),
        delivery_dispatcher=delivery_dispatcher,
        conversation_log=conversation_log,
    )


def _build_postprocess_service(
    config: ChatTaskAgentRuntimeConfig,
    callbacks: ChatTaskAgentRuntimeCallbacks,
    *,
    context_parts: ChatContextRuntimeParts,
    session_run_coordinator: SessionRunCoordinator,
    delivery_dispatcher: Any,
) -> ChatPostProcessService:
    return ChatPostProcessService(
        agent_id=config.agent_id,
        context_assembler=context_parts.context_assembler,
        get_event_emitter=callbacks.get_event_emitter,
        get_task_agent_manager=callbacks.get_task_agent_manager,
        get_source_hub=callbacks.get_source_hub,
        memory=config.memory,
        unified_memory=config.unified_memory,
        post_turn_understanding_service=config.post_turn_understanding_service,
        max_fact_memory=callbacks.max_fact_memory,
        trace_read_service=_build_chat_trace_read_service(),
        runtime_trace_store=config.runtime_trace_store,
        chat_store=config.chat_store,
        chat_read_service_factory=context_parts.chat_read_service_factory,
        complete_session_run=lambda session_id, run_id, revision: session_run_coordinator.complete_run_with_pending_inputs(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
        ),
        resolve_session_run_status=lambda session_id, run_id, revision: session_run_coordinator.get_run_status(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
        ),
        release_pending_inputs=callbacks.release_pending_inputs,
        response_rhythm_planner=ResponseRhythmPlanner(),
        event_bus=config.message_bus,
        deliver_final_response=(
            callbacks.deliver_final_response
            if delivery_dispatcher is not None
            else None
        ),
    )


def _build_chat_trace_read_service() -> Any:
    from magi.runtime_trace.chat_trace.read_service import ChatTraceReadService

    return ChatTraceReadService()


def _build_function_calling_orchestrator(
    config: ChatTaskAgentRuntimeConfig,
    *,
    context_parts: ChatContextRuntimeParts,
    postprocess_service: ChatPostProcessService,
) -> FunctionCallingOrchestrator:
    return FunctionCallingOrchestrator(
        llm_adapter=config.llm_adapter,
        active_model_provider=(
            (lambda: config.llm_pool.resolve(LLMScenario.CORE))
            if config.llm_pool is not None
            else None
        ),
        tool_registry=tool_registry,
        skill_runner=config.skill_runner,
        tool_result_callback=postprocess_service.record_tool_interaction,
        loop_event_callback=postprocess_service.record_tool_loop_fact,
        runtime_trace_store=config.runtime_trace_store,
        scenario_llm_pool=config.llm_pool,
        permission_gateway_provider=config.permission_gateway_provider,
        attachment_resolver=context_parts.attachment_resolver,
    )
