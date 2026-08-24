"""Runtime dependency assembly facade for the chat task agent."""

from __future__ import annotations

from .runtime_context_builder import build_chat_context_runtime_parts
from .runtime_contracts import (
    ChatTaskAgentRuntimeCallbacks,
    ChatTaskAgentRuntimeConfig,
    ChatTaskAgentRuntimeParts,
    default_chat_read_service_factory,
)
from .runtime_execution_builder import build_chat_execution_runtime_parts
from .runtime_handler_builder import build_chat_handler_runtime_parts


def build_chat_task_agent_runtime_parts(
    config: ChatTaskAgentRuntimeConfig,
    callbacks: ChatTaskAgentRuntimeCallbacks,
) -> ChatTaskAgentRuntimeParts:
    context_parts = build_chat_context_runtime_parts(config, callbacks)
    execution_parts = build_chat_execution_runtime_parts(
        config,
        callbacks,
        context_parts,
    )
    handler_parts = build_chat_handler_runtime_parts(
        config,
        callbacks,
        context_parts,
        execution_parts,
    )

    return ChatTaskAgentRuntimeParts(
        chat_read_service_factory=context_parts.chat_read_service_factory,
        prompt_context_assembler=context_parts.prompt_context_assembler,
        prompt_context_renderer=context_parts.prompt_context_renderer,
        chat_read_service=context_parts.chat_read_service,
        attachment_resolver=context_parts.attachment_resolver,
        context_retrieval_service=context_parts.context_retrieval_service,
        context_service=context_parts.context_service,
        context_assembler=context_parts.context_assembler,
        fact_classifier=context_parts.fact_classifier,
        prompt_service=context_parts.prompt_service,
        interruption_classifier=context_parts.interruption_classifier,
        session_run_coordinator=execution_parts.session_run_coordinator,
        transcript_summarizer=execution_parts.transcript_summarizer,
        postprocess_service=execution_parts.postprocess_service,
        function_calling_orchestrator=execution_parts.function_calling_orchestrator,
        handler_registry=handler_parts.handler_registry,
        coordinator=handler_parts.coordinator,
    )


__all__ = [
    "ChatTaskAgentRuntimeCallbacks",
    "ChatTaskAgentRuntimeConfig",
    "ChatTaskAgentRuntimeParts",
    "build_chat_task_agent_runtime_parts",
    "default_chat_read_service_factory",
]
