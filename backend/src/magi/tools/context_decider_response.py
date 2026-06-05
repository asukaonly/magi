"""LLM response parsing helpers for ContextDecider.

Phase B: returns RouteDecision (typed schema) instead of ContextDecision
(free-form). The parser tolerates legacy LLM outputs by falling back to
a safe-default RouteDecision when fields are missing or invalid.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..config.models import ThinkingDepth
from .context_routing import RouteDecision
from .context_routing.route_decision import (
    COMPLEXITY_VALUES,
    GRAPH_SHAPE_VALUES,
    NEEDS_ORCHESTRATION_VALUES,
    PROFILE_VALUES,
)

logger = logging.getLogger(__name__)


def _fallback_route_decision(reasoning: str = "Fallback") -> RouteDecision:
    """Safe-default RouteDecision returned on empty/garbled LLM output."""
    return RouteDecision(
        profile="chat",
        graph_shape="reply",
        complexity="simple",
        reasoning=reasoning,
    )


def _safe_get_literal(data: dict, key: str, allowed: frozenset[str], default: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value in allowed:
        return value
    return default


def _safe_get_list_str(data: dict, key: str) -> list[str]:
    value = data.get(key)
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str)]
    return []


def _safe_get_tuple_str(data: dict, key: str) -> tuple[str, ...]:
    return tuple(_safe_get_list_str(data, key))


def _safe_get_bool(data: dict, key: str, default: bool = False) -> bool:
    value = data.get(key)
    return value if isinstance(value, bool) else default


def _safe_get_thinking_depth(data: dict) -> ThinkingDepth:
    raw_depth = data.get("thinking_depth")
    if isinstance(raw_depth, str):
        try:
            return ThinkingDepth(raw_depth.lower())
        except ValueError:
            pass
    # Backward-compat: old prompts used `deep_thinking: bool`.
    if data.get("deep_thinking") is True:
        return ThinkingDepth.MEDIUM
    return ThinkingDepth.NONE


class ContextDeciderResponseMixin:
    """Parse context-decider LLM JSON responses into RouteDecision."""

    max_tools: int
    tool_registry: Any

    def _get_available_tools(self) -> list[dict[str, Any]]: ...

    def _parse_response(self, response: str) -> RouteDecision:
        """Parse LLM response into RouteDecision."""
        response = (response or "").strip()
        if not response:
            logger.warning("[ContextDecider] Empty LLM response")
            return _fallback_route_decision("Empty LLM response")
        if response in ("{", "}", "{}"):
            logger.warning(f"[ContextDecider] Incomplete LLM response: {response}")
            return _fallback_route_decision("Incomplete LLM response")

        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)
        if not json_match:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            logger.warning(f"[ContextDecider] No JSON object found in response")
            return _fallback_route_decision("No JSON in response")

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError as exc:
            logger.warning(f"[ContextDecider] JSON parse failed: {exc}")
            return _fallback_route_decision(f"JSON parse failed: {exc}")

        if not isinstance(data, dict):
            return _fallback_route_decision("Response is not a JSON object")

        try:
            return RouteDecision(
                profile=_safe_get_literal(data, "profile", PROFILE_VALUES, "chat"),
                graph_shape=_safe_get_literal(data, "graph_shape", GRAPH_SHAPE_VALUES, "reply"),
                complexity=_safe_get_literal(data, "complexity", COMPLEXITY_VALUES, "simple"),
                tools=_safe_get_list_str(data, "tools")[: self.max_tools],
                may_write=_safe_get_bool(data, "may_write"),
                reasoning=str(data.get("reasoning") or ""),
                thinking_depth=_safe_get_thinking_depth(data),
                memory_route=str(data.get("memory_route") or "none"),
                needs_orchestration=(
                    data["needs_orchestration"]
                    if isinstance(data.get("needs_orchestration"), str)
                    and data.get("needs_orchestration") in NEEDS_ORCHESTRATION_VALUES
                    # Backward-compat: infer from the legacy graph_shape when the
                    # router hasn't emitted the explicit three-state field yet.
                    else ("required" if data.get("graph_shape") == "plan_fanout" else "none")
                ),
                register=str(data.get("register")) if data.get("register") else None,
                active_trigger_ids=_safe_get_tuple_str(data, "active_trigger_ids"),
                situation_strength=str(data.get("situation_strength") or "ordinary"),
                quiet_hour_hints=_safe_get_tuple_str(data, "quiet_hour_hints"),
            )
        except (ValueError, TypeError) as exc:
            logger.warning(f"[ContextDecider] RouteDecision construction failed: {exc}")
            return _fallback_route_decision(f"Construction failed: {exc}")


__all__ = ["ContextDeciderResponseMixin"]
