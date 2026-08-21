"""Per-turn route resolution for chat task-agent execution."""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from ....tools.context_routing import RouteDecision
from ....tools.system_tools import resolve_resident_system_tools
from ...orchestration_plan import OrchestrationPlan
from ..common import ExecutionMode
from .tool_exposure_policy import ToolExposurePolicy, default_tool_exposure_policy

SHAPE_REPLY = "reply"
SHAPE_TOOL_LOOP = "tool_loop"
SHAPE_PLAN_FANOUT = "plan_fanout"

ORCH_NONE = "none"
ORCH_MAYBE = "maybe"
ORCH_REQUIRED = "required"

FALLBACK_TOOLS: tuple[str, ...] = ("web-search", "find-relevant-tools")


@dataclass(slots=True, frozen=True)
class TurnRouteResolution:
    """Final route shape for a chat turn before handler dispatch."""

    route_decision: RouteDecision
    selected_tools: list[str]
    execution_mode: ExecutionMode
    orchestration_plan: OrchestrationPlan


def derive_execution_shape(
    *,
    has_image_attachments: bool,
    orchestration: str,
    has_tools: bool,
) -> str:
    """Return the execution shape for this turn."""
    if has_image_attachments:
        return SHAPE_REPLY
    if orchestration == ORCH_REQUIRED:
        return SHAPE_PLAN_FANOUT
    if has_tools:
        return SHAPE_TOOL_LOOP
    return SHAPE_REPLY


def _registered_tool_names(registered_tools: Collection[str] | None) -> set[str]:
    return {str(tool).strip() for tool in (registered_tools or set()) if str(tool).strip()}


def _append_if_registered(
    tools: list[str],
    tool_name: str,
    registered_tools: set[str],
) -> None:
    if tool_name in registered_tools and tool_name not in tools:
        tools.append(tool_name)


def _has_image_attachment(effective_attachments: Sequence[Any]) -> bool:
    return any(
        isinstance(item, dict) and str(item.get("kind") or "").strip() == "image"
        for item in effective_attachments
    )


class TurnRouteResolver:
    """Resolve ContextDecider output into final per-turn execution choices."""

    def __init__(
        self,
        *,
        tool_exposure_policy: ToolExposurePolicy = default_tool_exposure_policy,
    ) -> None:
        self._tool_exposure_policy = tool_exposure_policy

    def resolve_intent_route(
        self,
        *,
        user_message: str,
        route_decision: RouteDecision,
        registered_tools: Collection[str] | None,
        effective_attachments: Sequence[Any],
        force_direct_external: bool,
    ) -> TurnRouteResolution:
        registered = _registered_tool_names(registered_tools)
        has_image_attachments = _has_image_attachment(effective_attachments)
        selected_tools = [] if has_image_attachments else list(route_decision.tools)

        if not has_image_attachments and force_direct_external:
            selected_tools = self._prefer_direct_external_tools(
                selected_tools,
                registered_tools=registered,
            )

        if (
            not has_image_attachments
            and getattr(route_decision, "tool_need", "direct" if selected_tools else "none")
            == "discover"
        ):
            _append_if_registered(selected_tools, "find-relevant-tools", registered)

        if selected_tools:
            selected_tools = self._append_fallback_tools(
                selected_tools,
                registered_tools=registered,
            )

        return self.finalize_intent_route(
            route_decision=route_decision,
            selected_tools=selected_tools,
            has_image_attachments=has_image_attachments,
            force_direct_external=force_direct_external,
        )

    def finalize_intent_route(
        self,
        *,
        route_decision: RouteDecision,
        selected_tools: list[str],
        has_image_attachments: bool,
        force_direct_external: bool,
    ) -> TurnRouteResolution:
        orchestration = route_decision.needs_orchestration
        if orchestration == ORCH_NONE and route_decision.graph_shape == SHAPE_PLAN_FANOUT:
            orchestration = ORCH_REQUIRED
        if force_direct_external and orchestration == ORCH_REQUIRED:
            orchestration = ORCH_NONE

        effective_graph_shape = derive_execution_shape(
            has_image_attachments=has_image_attachments,
            orchestration=orchestration,
            has_tools=bool(selected_tools),
        )
        decision = route_decision
        if effective_graph_shape != route_decision.graph_shape:
            decision = dataclasses.replace(route_decision, graph_shape=effective_graph_shape)

        if effective_graph_shape == SHAPE_PLAN_FANOUT:
            execution_mode = ExecutionMode.ORCHESTRATION_LAUNCH
        elif effective_graph_shape == SHAPE_TOOL_LOOP:
            execution_mode = ExecutionMode.FUNCTION_CALLING
        else:
            execution_mode = ExecutionMode.DIRECT_LLM

        return TurnRouteResolution(
            route_decision=decision,
            selected_tools=list(selected_tools),
            execution_mode=execution_mode,
            orchestration_plan=OrchestrationPlan.from_route_decision(decision),
        )

    def resolve_execution_tools(
        self,
        *,
        requested_tools: Sequence[str],
        route_decision: RouteDecision | None,
        tool_registry: Any | None,
        session_key: str,
    ) -> list[str]:
        selected_tools = list(requested_tools)
        registered_tools: set[str] | None = None
        if tool_registry is not None:
            try:
                registered_tools = set(tool_registry.list_tools())
            except Exception:
                registered_tools = None

        if tool_registry is not None:
            for resident_tool in resolve_resident_system_tools(tool_registry):
                if resident_tool not in selected_tools:
                    selected_tools.append(resident_tool)

        if tool_registry is None or not hasattr(self._tool_exposure_policy, "resolve"):
            return selected_tools

        return self._tool_exposure_policy.resolve(
            session_key=session_key,
            requested_tools=selected_tools,
            registered_tools=registered_tools,
            may_write=bool(getattr(route_decision, "may_write", False)),
        )

    def _append_fallback_tools(
        self,
        selected_tools: list[str],
        *,
        registered_tools: set[str],
    ) -> list[str]:
        tools = list(selected_tools)
        for fallback_tool in FALLBACK_TOOLS:
            _append_if_registered(tools, fallback_tool, registered_tools)
        return tools

    def _prefer_direct_external_tools(
        self,
        selected_tools: list[str],
        *,
        registered_tools: set[str],
    ) -> list[str]:
        tools = [tool for tool in selected_tools if tool != "agent"]
        _append_if_registered(tools, "web-search", registered_tools)
        if "web-fetch" in selected_tools:
            _append_if_registered(tools, "web-fetch", registered_tools)
        return tools


__all__ = [
    "FALLBACK_TOOLS",
    "ORCH_MAYBE",
    "ORCH_NONE",
    "ORCH_REQUIRED",
    "SHAPE_PLAN_FANOUT",
    "SHAPE_REPLY",
    "SHAPE_TOOL_LOOP",
    "TurnRouteResolution",
    "TurnRouteResolver",
    "derive_execution_shape",
]
