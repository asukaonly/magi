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
                thinking_depth=ThinkingDepth.NONE,
                reasoning="Empty LLM response",
                orchestration_strategy=self._default_orchestration_strategy(),
            )

        if response == "{" or response == "{}":
            logger.warning(f"[ContextDecider] Incomplete LLM response: {response}")
            return ContextDecision(
                intent="unknown",
                tools=[],
                thinking_depth=ThinkingDepth.NONE,
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

                register = data.get("register")
                if register is not None and not isinstance(register, str):
                    register = None
                elif isinstance(register, str):
                    register = register.strip().lower() or None
                if register not in (None, "casual", "task", "analysis", "emotional", "crisis"):
                    logger.warning("[ContextDecider] Unknown register '%s' from LLM; ignoring", register)
                    register = None

                raw_trigger_ids = data.get("active_trigger_ids") or []
                if not isinstance(raw_trigger_ids, list):
                    raw_trigger_ids = []
                active_trigger_ids: list[str] = []
                for trigger_id in raw_trigger_ids:
                    if isinstance(trigger_id, str) and trigger_id.strip():
                        active_trigger_ids.append(trigger_id.strip())
                    if len(active_trigger_ids) >= 2:
                        break

                situation_strength = data.get("situation_strength", "ordinary")
                if not isinstance(situation_strength, str):
                    situation_strength = "ordinary"
                situation_strength = situation_strength.strip().lower() or "ordinary"
                if situation_strength not in {"ordinary", "strong", "crisis"}:
                    situation_strength = "ordinary"

                raw_hints = data.get("quiet_hour_hints") or []
                if not isinstance(raw_hints, list):
                    raw_hints = []
                quiet_hour_hints: list[str] = [
                    str(hint).strip() for hint in raw_hints if isinstance(hint, str) and str(hint).strip()
                ]

                return ContextDecision(
                    intent=intent,
                    tools=valid_tools,
                    thinking_depth=thinking_depth,
                    reasoning=reasoning,
                    orchestration_strategy=orchestration_strategy,
                    register=register,
                    active_trigger_ids=active_trigger_ids,
                    situation_strength=situation_strength,
                    quiet_hour_hints=quiet_hour_hints,
                )
            except json.JSONDecodeError as e:
                logger.warning(f"[ContextDecider] JSON decode error: {e}")
            except ValueError as e:
                logger.warning(f"[ContextDecider] Invalid response structure: {e}")

        logger.warning(f"[ContextDecider] Failed to parse response: {response[:200]}")
        return ContextDecision(
            intent="unknown",
            tools=[],
            thinking_depth=ThinkingDepth.NONE,
            reasoning="Failed to parse LLM response",
            orchestration_strategy=self._default_orchestration_strategy(),
        )


__all__ = ["ContextDeciderResponseMixin"]
