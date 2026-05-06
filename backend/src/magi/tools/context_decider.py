"""
Context Decider - LLM-powered context and tool selection

Decides:
1. User intent classification
2. Top 5 most relevant tools for the current request
3. Memory layer to retrieve (TODO)

This replaces the old ToolSelector for better tool selection.
"""
import logging
from typing import Any, Optional

from ..config.constants import DEFAULT_THINKING_TOKENS
from ..config.models import LLMScenario, ThinkingDepth
from ..llm.base import LLMAdapter
from ..llm.provider_bridge import LLMProviderBridge
from ..utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response
from .context_decider_context import ContextDeciderContext
from .context_decider_fallback import ContextDeciderFallbackMixin
from .context_decider_guidance import ContextDeciderGuidanceMixin
from .context_decider_prompt import build_context_decider_prompt
from .context_decider_response import ContextDeciderResponseMixin
from .context_decider_system_prompt import CONTEXT_DECIDER_SYSTEM_PROMPT
from .context_decider_trace import ContextDeciderTraceMixin
from .context_routing import MEMORY_RETRIEVAL_TRIGGERS, ContextDecision, MemoryGuidance
from .registry import ToolRegistry

logger = logging.getLogger(__name__)
llm_logger = get_llm_logger('context_decider')


class ContextDecider(
    ContextDeciderGuidanceMixin,
    ContextDeciderResponseMixin,
    ContextDeciderFallbackMixin,
    ContextDeciderTraceMixin,
):
    """
    Context Decision Module

    Analyzes user request and selects the most relevant tools.
    Uses LLM to understand intent and match with available tools.
    """

    system_PROMPT = CONTEXT_DECIDER_SYSTEM_PROMPT

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_adapter: Optional[LLMAdapter] = None,
        llm_pool=None,
        max_tools: int = 5,
    ):
        """
        initialize the Context Decider

        Args:
            tool_registry: Tool registry instance
            llm_adapter: LLM adapter for analysis
            max_tools: Maximum number of tools to select
        """
        self.tool_registry = tool_registry
        self._llm_pool = llm_pool
        self.llm = llm_adapter or self._resolve_llm_from_pool()
        self.provider_bridge = LLMProviderBridge(self.llm) if self.llm else None
        self.max_tools = max_tools

    def _resolve_llm_from_pool(self) -> Optional[LLMAdapter]:
        if self._llm_pool is None:
            return None
        return self._llm_pool.get(LLMScenario.CONTEXT_DECIDER)

    async def decide(
        self,
        user_message: str,
        context: Optional[ContextDeciderContext] = None,
    ) -> ContextDecision:
        """
        Analyze user request and decide on tools

        Args:
            user_message: User's message
            context: additional context (environment info, etc.)

        Returns:
            ContextDecision with selected tools
        """
        pooled_llm = self._resolve_llm_from_pool()
        if pooled_llm is not None and pooled_llm is not self.llm:
            self.llm = pooled_llm
            self.provider_bridge = LLMProviderBridge(pooled_llm)

        if not self.llm:
            logger.warning("[ContextDecider] LLM not available")
            return ContextDecision(
                intent="unknown",
                tools=[],
                thinking_depth=ThinkingDepth.NONE,
                reasoning="LLM not available",
                orchestration_strategy=self._default_orchestration_strategy(),
            )

        available_tools = self._get_available_tools()
        user_prompt = self._build_prompt(user_message, available_tools, context)

        try:
            import time
            import uuid

            request_id = str(uuid.uuid4())[:8]
            start_time = time.time()

            log_llm_request(
                llm_logger,
                request_id=request_id,
                model=self.llm.model_name,
                system_prompt=self.system_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            provider_response = await self.provider_bridge.chat_response(
                system_prompt=self.system_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=DEFAULT_THINKING_TOKENS,
                temperature=0.3,
                disable_thinking=True,
                event_context={
                    "request_id": request_id,
                    "request_kind": "context_decider",
                    "agent_id": "context_decider",
                },
            )
            response = provider_response.content

            if not response or not response.strip():
                logger.warning("[ContextDecider] LLM returned empty response, using rule-based fallback")
                return self._rule_based_fallback(user_message, context)  # type: ignore[arg-type]

            stripped = response.strip()
            if stripped in ("{", "}", "{}"):
                logger.warning(f"[ContextDecider] LLM returned incomplete response: {stripped}, using rule-based fallback")
                return self._rule_based_fallback(user_message, context)  # type: ignore[arg-type]

            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=response,
                success=True,
                duration_ms=duration_ms,
            )

            decision = self._parse_response(response)
            decision = self._apply_research_guardrail(
                user_message=user_message,
                decision=decision,
                available_tools=available_tools,
            )
            decision = self._apply_memory_guidance(
                user_message=user_message,
                context=context,  # type: ignore[arg-type]
                decision=decision,
                available_tools=available_tools,
            )
            decision.llm_trace = self._build_llm_trace(
                metadata=provider_response.metadata,
                disable_thinking=True,
                duration_ms=duration_ms,
            )

            logger.info(
                f"[ContextDecider] Decision made | Intent: {decision.intent} | "
                f"Tools: {decision.tools} | Thinking: {decision.thinking_depth.value} | Reasoning: {decision.reasoning}"
            )
            logger.debug(f"[ContextDecider] Raw LLM response: {response[:500]}")

            return decision

        except Exception as e:
            logger.error(f"[ContextDecider] Decision failed: {e}")
            return ContextDecision(
                intent="error",
                tools=[],
                thinking_depth=ThinkingDepth.NONE,
                reasoning=f"error: {str(e)}",
                orchestration_strategy=self._default_orchestration_strategy(),
            )

    def _get_available_tools(self) -> list[dict[str, Any]]:
        """Get list of available tools with metadata"""
        tools_info = self.tool_registry.get_all_tools_info()
        return [
            {
                "name": tool.get("name"),
                "description": tool.get("description"),
                "type": tool.get("type", "tool"),
            }
            for tool in tools_info
            if tool.get("type") != "skill"
        ]

    def _build_prompt(
        self,
        user_message: str,
        available_tools: list[dict[str, Any]],
        context: Optional[ContextDeciderContext],
    ) -> str:
        """Build the prompt for context decision"""
        return build_context_decider_prompt(
            tool_registry=self.tool_registry,
            user_message=user_message,
            available_tools=available_tools,
            context=context,
        )


__all__ = [
    "ContextDecider",
    "ContextDecision",
    "MemoryGuidance",
    "MEMORY_RETRIEVAL_TRIGGERS",
]
