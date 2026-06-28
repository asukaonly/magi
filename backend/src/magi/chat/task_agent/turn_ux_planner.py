"""Presentation planning for chat task-agent turns."""

from __future__ import annotations

import random

from magi.agent.task_agents.common import ExecutionMode
from magi.agent.task_agents.handlers.contracts import (
    AssistantSurfaceMode,
    ThinkingIndicatorMode,
    TraceDisplayMode,
    TurnUXPlan,
)
from magi.personality.active_persona import get_current_personality_config
from magi.tools.context_routing import RouteDecision


class TurnUXPlanner:
    """Build the chat-facing presentation plan for a routed turn."""

    _REACTION_ONLY_ACKS = {
        "嗯",
        "嗯嗯",
        "恩",
        "哦",
        "ok",
        "okay",
        "好的",
        "收到",
        "明白",
    }

    _INTERIM_FALLBACK_LINES: dict[str, dict[str, list[str]]] = {
        "zh": {
            "orchestration_launch": ["让我仔细想想再回复你。"],
            "explore_task": ["我去仔细看一下，稍后把结果给你。"],
        },
        "en": {
            "orchestration_launch": ["Let me think this through and check for you."],
            "explore_task": ["Let me inspect this in detail and I will come back with the result."],
        },
    }

    def build(
        self,
        *,
        user_message: str,
        execution_mode: ExecutionMode,
        tools: list[str],
        route_decision: RouteDecision | None = None,
    ) -> TurnUXPlan:
        """Return the user-visible chat surface behavior for one turn."""
        normalized_message = str(user_message or "").strip().lower()
        if execution_mode == ExecutionMode.FACT_ONLY:
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.NONE,
                thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                trace_display_mode=TraceDisplayMode.NONE,
            )
        if execution_mode == ExecutionMode.DIRECT_LLM:
            if normalized_message in self._REACTION_ONLY_ACKS:
                return TurnUXPlan(
                    assistant_surface_mode=AssistantSurfaceMode.REACTION_ONLY,
                    thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                    trace_display_mode=TraceDisplayMode.NONE,
                    reaction_style="acknowledge",
                )
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.FINAL_ONLY,
                thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                trace_display_mode=TraceDisplayMode.COLLAPSIBLE,
            )
        if execution_mode == ExecutionMode.FUNCTION_CALLING:
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.FINAL_ONLY,
                thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                trace_display_mode=TraceDisplayMode.PROMINENT,
                allow_trace_collapse=bool(tools),
            )
        if execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH:
            is_explore = bool(
                route_decision is not None
                and route_decision.profile == "explore"
                and route_decision.graph_shape == "plan_fanout"
            )
            interim_text = self._resolve_interim_text(
                mode_key="explore_task" if is_explore else "orchestration_launch",
                user_message=user_message,
            )
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.INTERIM_THEN_FINAL,
                thinking_indicator=ThinkingIndicatorMode.SUBTLE,
                trace_display_mode=TraceDisplayMode.PROMINENT,
                allow_trace_collapse=True,
                interim_text=interim_text,
            )
        if execution_mode in {
            ExecutionMode.ORCHESTRATION_UPDATE,
            ExecutionMode.EXPLORE_TASK_RENDER,
        }:
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.FINAL_ONLY,
                thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                trace_display_mode=TraceDisplayMode.PROMINENT,
                allow_trace_collapse=True,
            )
        return TurnUXPlan()

    @staticmethod
    def _detect_message_language(message: str) -> str:
        """Return ``"zh"`` if the message contains CJK, otherwise ``"en"``."""
        for ch in message or "":
            if "\u4e00" <= ch <= "\u9fff":
                return "zh"
        return "en"

    def _resolve_interim_text(self, *, mode_key: str, user_message: str) -> str:
        """Pick the interim placeholder line for the active persona."""
        persona_config = None
        try:
            persona_config = get_current_personality_config()
        except Exception:  # pragma: no cover - defensive, persona cache should never raise
            persona_config = None
        persona_lines: list[str] = []
        if persona_config is not None:
            persona_lines = list(getattr(persona_config, "interim_lines", {}).get(mode_key, []))
        if persona_lines:
            return random.choice(persona_lines)
        lang = self._detect_message_language(user_message)
        fallback = self._INTERIM_FALLBACK_LINES.get(lang, {}).get(mode_key)
        if fallback:
            return random.choice(fallback)
        return self._INTERIM_FALLBACK_LINES["en"]["orchestration_launch"][0]


__all__ = ["TurnUXPlanner"]
