"""LLM response parsing helpers for ContextDecider."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..config.models import ThinkingDepth
from .context_routing import ContextDecision

logger = logging.getLogger(__name__)


class ContextDeciderResponseMixin:
    """Parse context-decider LLM JSON responses."""

    max_tools: int
    tool_registry: Any

    def _default_orchestration_strategy(self, tools: list[str] | None = None, user_lower: str = "") -> dict[str, Any]: ...

    def _get_available_tools(self) -> list[dict[str, Any]]: ...

    def _normalize_orchestration_strategy(self, payload: Any) -> dict[str, Any]: ...

    def _parse_response(self, response: str) -> ContextDecision:
        """Parse LLM response into ContextDecision"""
        response = response.strip()

        if not response:
            logger.warning("[ContextDecider] Empty LLM response")
            return ContextDecision(
                intent="unknown",
                tools=[],
                deep_thinking=False,
                reasoning="Empty LLM response",
                orchestration_strategy=self._default_orchestration_strategy(),
            )

        if response == "{" or response == "{}":
            logger.warning(f"[ContextDecider] Incomplete LLM response: {response}")
            return ContextDecision(
                intent="unknown",
                tools=[],
                deep_thinking=False,
                reasoning="Incomplete LLM response",
                orchestration_strategy=self._default_orchestration_strategy(),
            )

        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)

        if not json_match:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)

        if json_match:
            try:
                json_str = json_match.group()
                data = json.loads(json_str)

                if not isinstance(data, dict):
                    raise ValueError("Response is not a JSON object")

                intent = data.get("intent", "unknown")
                tools = data.get("tools", [])
                reasoning = data.get("reasoning", "")
                orchestration_strategy = self._normalize_orchestration_strategy(
                    data.get("orchestration_strategy")
                )

                raw_depth = data.get("thinking_depth")
                thinking_depth: ThinkingDepth | None = None
                if isinstance(raw_depth, str):
                    try:
                        thinking_depth = ThinkingDepth(raw_depth.lower())
                    except ValueError:
                        pass
                if thinking_depth is None:
                    deep_thinking = data.get("deep_thinking", False)
                    thinking_depth = ThinkingDepth.HIGH if deep_thinking else ThinkingDepth.NONE

                valid_tools = []
                available = {t["name"] for t in self._get_available_tools()}
                for tool in tools[:self.max_tools]:
                    if tool in available:
                        valid_tools.append(tool)
                    elif tool.startswith("/") and self.tool_registry.is_skill(tool.lstrip("/")):
                        valid_tools.append(tool)

                return ContextDecision(
                    intent=intent,
                    tools=valid_tools,
                    thinking_depth=thinking_depth,
                    reasoning=reasoning,
                    orchestration_strategy=orchestration_strategy,
                )
            except json.JSONDecodeError as e:
                logger.warning(f"[ContextDecider] JSON decode error: {e}")
            except ValueError as e:
                logger.warning(f"[ContextDecider] Invalid response structure: {e}")

        logger.warning(f"[ContextDecider] Failed to parse response: {response[:200]}")
        return ContextDecision(
            intent="unknown",
            tools=[],
            deep_thinking=False,
            reasoning="Failed to parse LLM response",
            orchestration_strategy=self._default_orchestration_strategy(),
        )


__all__ = ["ContextDeciderResponseMixin"]
