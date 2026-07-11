"""Context-facing runtime assembly for the chat task agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from magi.agent.run.ports import LazyAttachmentResolver
from magi.agent.runtime.types import TaskAgentType
from magi.chat import ChatReadService
from magi.chat.task_agent.context_assembler import ChatContextAssembler
from magi.chat.task_agent.fact_classifier import ChatFactClassifier
from magi.chat.task_agent.interruption_classifier import InterruptionClassifier
from magi.chat.task_agent.prompt_service import ChatPromptService
from magi.context import (
    ContextAssemblyService,
    ContextRetrievalService,
    PromptContextAssembler,
    PromptContextRenderer,
)
from magi.config.models import LLMScenario
from magi.llm.model_context import ModelContextProfile, unknown_model_context
from magi.context.user_profile_service import UserProfileService
from magi.tools.context_decider import ContextDecider
from magi.tools.registry import tool_registry
from magi.utils.runtime import get_runtime_paths

from .runtime_contracts import (
    ChatTaskAgentRuntimeCallbacks,
    ChatTaskAgentRuntimeConfig,
    default_chat_read_service_factory,
)


@dataclass(slots=True)
class ChatContextRuntimeParts:
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
    model_context_provider: Callable[[], ModelContextProfile]


def build_chat_context_runtime_parts(
    config: ChatTaskAgentRuntimeConfig,
    callbacks: ChatTaskAgentRuntimeCallbacks,
) -> ChatContextRuntimeParts:
    chat_read_service_factory = (
        config.chat_read_service_factory or default_chat_read_service_factory
    )
    prompt_context_assembler = PromptContextAssembler(
        user_profile_service=UserProfileService(unified_memory=config.unified_memory),
    )
    prompt_context_renderer = PromptContextRenderer()
    context_retrieval_service = ContextRetrievalService(
        unified_memory=config.unified_memory,
        retrieval_service=config.hybrid_retrieval_service,
    )

    model_context_provider = _build_model_context_provider(config)
    return ChatContextRuntimeParts(
        chat_read_service_factory=chat_read_service_factory,
        context_decider=_build_context_decider(config),
        prompt_context_assembler=prompt_context_assembler,
        prompt_context_renderer=prompt_context_renderer,
        chat_read_service=chat_read_service_factory(),
        attachment_resolver=LazyAttachmentResolver(chat_read_service_factory),
        context_retrieval_service=context_retrieval_service,
        context_service=_build_context_service(
            config,
            callbacks,
            prompt_context_assembler=prompt_context_assembler,
            prompt_context_renderer=prompt_context_renderer,
            context_retrieval_service=context_retrieval_service,
        ),
        context_assembler=_build_context_assembler(config, chat_read_service_factory),
        fact_classifier=ChatFactClassifier(),
        prompt_service=ChatPromptService(
            llm_adapter=config.llm_adapter,
            llm_pool=config.llm_pool,
        ),
        interruption_classifier=InterruptionClassifier(
            llm_adapter=config.llm_adapter,
            llm_pool=config.llm_pool,
        ),
        model_context_provider=model_context_provider,
    )


def _build_model_context_provider(
    config: ChatTaskAgentRuntimeConfig,
) -> Callable[[], ModelContextProfile]:
    if config.llm_pool is not None:
        return lambda: config.llm_pool.resolve(LLMScenario.CORE).context
    return lambda: unknown_model_context(config.llm_adapter)


def _build_context_decider(config: ChatTaskAgentRuntimeConfig) -> ContextDecider:
    return ContextDecider(
        tool_registry=tool_registry,
        llm_adapter=config.llm_adapter,
        llm_pool=config.llm_pool,
    )


def _build_context_service(
    config: ChatTaskAgentRuntimeConfig,
    callbacks: ChatTaskAgentRuntimeCallbacks,
    *,
    prompt_context_assembler: PromptContextAssembler,
    prompt_context_renderer: PromptContextRenderer,
    context_retrieval_service: ContextRetrievalService,
) -> ContextAssemblyService:
    return ContextAssemblyService(
        agent_id=config.agent_id,
        agent_type=TaskAgentType.CHAT.value,
        prompt_context_assembler=prompt_context_assembler,
        prompt_context_renderer=prompt_context_renderer,
        retrieval_memory_provider=context_retrieval_service.build_retrieved_memory_payload,
        memory=config.memory,
        session_workspace_provider=callbacks.session_workspace_provider,
    )


def _build_context_assembler(
    config: ChatTaskAgentRuntimeConfig,
    chat_read_service_factory: Callable[[], ChatReadService],
) -> ChatContextAssembler:
    runtime_paths = get_runtime_paths()
    return ChatContextAssembler(
        l1_db_path=runtime_paths.l1_memory_db_path,
        history_cache_max_sessions=config.history_cache_max_sessions,
        history_fetch_limit=config.history_fetch_limit,
        chat_store=config.chat_store,
        chat_read_service_factory=chat_read_service_factory,
        scenario_llm_pool=config.llm_pool,
        llm_adapter=config.llm_adapter,
    )
