"""
Context Decider - LLM-powered context and tool selection

Decides:
1. User intent classification
2. Top 5 most relevant tools for the current request
3. Memory retrieval route and whether to expose the memory query tool

This replaces the old ToolSelector for better tool selection.
"""

import dataclasses
import logging
import time
import uuid
from typing import Any, Optional

from ..config.constants import DEFAULT_THINKING_TOKENS
from ..config.models import LLMScenario
from ..llm.base import LLMAdapter
from ..llm.provider_bridge import LLMProviderBridge
from ..utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response
from ..utils.diagnostic_logging import full_content_logging_enabled
from .context_decider_context import ContextDeciderContext
from .context_decider_fallback import ContextDeciderFallbackMixin
from .context_decider_guidance import ContextDeciderGuidanceMixin
from .context_decider_prompt import build_context_decider_prompt
from .context_decider_response import ContextDeciderResponseMixin
from .context_decider_system_prompt import CONTEXT_DECIDER_SYSTEM_PROMPT
from .context_decider_trace import ContextDeciderTraceMixin
from .context_routing import MEMORY_RETRIEVAL_TRIGGERS, MemoryGuidance, RouteDecision
from .registry import ToolRegistry

logger = logging.getLogger(__name__)
llm_logger = get_llm_logger("context_decider")


def _new_request_id() -> str:
    return str(uuid.uuid4())[:8]


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
    ) -> RouteDecision:
        """
        Analyze user request and decide on tools

        Args:
            user_message: User's message
            context: additional context (environment info, etc.)

        Returns:
            RouteDecision with selected tools
        """
        self._refresh_llm_from_pool()

        if not self.llm:
            logger.warning("[ContextDecider] LLM not available")
            return self._no_llm_decision()

        available_tools = self._get_available_tools()
        user_prompt = self._build_prompt(user_message, available_tools, context)

        try:
            return await self._decide_with_llm(
                user_message=user_message,
                context=context,
                available_tools=available_tools,
                user_prompt=user_prompt,
            )
        except Exception as e:
            logger.error(f"[ContextDecider] Decision failed: {e}")
            return self._error_decision(e)

    def _refresh_llm_from_pool(self) -> None:
        pooled_llm = self._resolve_llm_from_pool()
        if pooled_llm is not None and pooled_llm is not self.llm:
            self.llm = pooled_llm
            self.provider_bridge = LLMProviderBridge(pooled_llm)

    def _no_llm_decision(self) -> RouteDecision:
        return RouteDecision(
            profile="chat",
            graph_shape="reply",
            complexity="simple",
            reasoning="LLM not available",
        )

    def _error_decision(self, error: Exception) -> RouteDecision:
        return RouteDecision(
            profile="chat",
            graph_shape="reply",
            complexity="simple",
            reasoning=f"error: {str(error)}",
        )

    async def _decide_with_llm(
        self,
        *,
        user_message: str,
        context: Optional[ContextDeciderContext],
        available_tools: list[dict[str, Any]],
        user_prompt: str,
    ) -> RouteDecision:
        request_id = _new_request_id()
        start_time = time.time()
        self._log_request(request_id, user_prompt)

        provider_response = await self._call_provider(request_id, user_prompt)
        response = provider_response.content

        fallback = self._fallback_for_bad_response(response, user_message, context)
        if fallback is not None:
            return fallback

        duration_ms = int((time.time() - start_time) * 1000)
        log_llm_response(
            llm_logger,
            request_id=request_id,
            response=response,
            success=True,
            duration_ms=duration_ms,
        )

        decision = self._finalize_decision(
            user_message=user_message,
            context=context,
            available_tools=available_tools,
            response=response,
            metadata=provider_response.metadata,
            duration_ms=duration_ms,
        )
        self._log_decision(decision, response)
        return decision

    def _log_request(self, request_id: str, user_prompt: str) -> None:
        log_llm_request(
            llm_logger,
            request_id=request_id,
            model=self.llm.model_name,
            system_prompt=self.system_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

    async def _call_provider(self, request_id: str, user_prompt: str):
        return await self.provider_bridge.chat_response(
            system_prompt=self.system_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=DEFAULT_THINKING_TOKENS,
            temperature=0.3,
            disable_thinking=True,
            # Routing system prompt is a constant — cache it (marker vendors).
            cache_system=True,
            event_context={
                "request_id": request_id,
                "request_kind": "context_decider",
                "agent_id": "context_decider",
            },
        )

    def _fallback_for_bad_response(
        self,
        response: str,
        user_message: str,
        context: Optional[ContextDeciderContext],
    ) -> RouteDecision | None:
        if not response or not response.strip():
            logger.warning(
                "[ContextDecider] LLM returned empty response, using rule-based fallback"
            )
            return self._rule_based_fallback(user_message, context)  # type: ignore[arg-type]

        stripped = response.strip()
        if stripped in ("{", "}", "{}"):
            logger.warning(
                f"[ContextDecider] LLM returned incomplete response: {stripped}, using rule-based fallback"
            )
            return self._rule_based_fallback(user_message, context)  # type: ignore[arg-type]

        return None

    def _finalize_decision(
        self,
        *,
        user_message: str,
        context: Optional[ContextDeciderContext],
        available_tools: list[dict[str, Any]],
        response: str,
        metadata: dict[str, Any],
        duration_ms: int,
    ) -> RouteDecision:
        decision = self._parse_response(response)
        decision = self._apply_memory_guidance(
            user_message=user_message,
            context=context,  # type: ignore[arg-type]
            decision=decision,
            available_tools=available_tools,
        )
        return self._attach_trace(
            decision=decision,
            metadata=metadata,
            duration_ms=duration_ms,
            user_message=user_message,
            response=response,
        )

    def _attach_trace(
        self,
        *,
        decision: RouteDecision,
        metadata: dict[str, Any],
        duration_ms: int,
        user_message: str,
        response: str,
    ) -> RouteDecision:
        trace_metadata = self._build_llm_trace(
            metadata=metadata,
            disable_thinking=True,
            duration_ms=duration_ms,
        )
        if full_content_logging_enabled():
            trace_metadata.setdefault("request_preview", user_message[:240])
            trace_metadata.setdefault("response_preview", response[:240])
        return dataclasses.replace(
            decision,
            llm_trace={**decision.llm_trace, **trace_metadata},
        )

    def _log_decision(self, decision: RouteDecision, response: str) -> None:
        if full_content_logging_enabled():
            logger.info(
                f"[ContextDecider] Decision made | Profile: {decision.profile} | "
                f"Graph: {decision.graph_shape} | Tools: {decision.tools} | "
                f"Thinking: {decision.thinking_depth.value} | Reasoning: {decision.reasoning}"
            )
            logger.debug(f"[ContextDecider] Raw LLM response: {response[:500]}")
            return
        logger.info(
            "[ContextDecider] Decision made | Profile: %s | Graph: %s | "
            "Tools: %s | Thinking: %s | Response chars: %d",
            decision.profile,
            decision.graph_shape,
            decision.tools,
            decision.thinking_depth.value,
            len(response),
        )

    def _get_available_tools(self) -> list[dict[str, Any]]:
        """Get list of available CAPABILITY tools with metadata.

        Resident runtime-control / system tools (ADR-0005 §4) are excluded:
        they are always available to the main LLM's tool loop, so the router
        must not spend prompt budget reasoning about whether to select them.
        """
        from magi.tools.system_tools import resolve_resident_system_tools

        resident = set(resolve_resident_system_tools(self.tool_registry))
        tools_info = self.tool_registry.get_all_tools_info()
        return [
            {
                "name": tool.get("name"),
                "description": tool.get("description"),
                "type": tool.get("type", "tool"),
            }
            for tool in tools_info
            if tool.get("type") != "skill" and tool.get("name") not in resident
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
    "RouteDecision",
    "MemoryGuidance",
    "MEMORY_RETRIEVAL_TRIGGERS",
]
