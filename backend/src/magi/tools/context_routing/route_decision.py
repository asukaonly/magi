"""RouteDecision: strict typed schema for the chat router LLM output.

The router LLM emits a JSON object matching this schema; downstream
consumers receive a typed ``RouteDecision`` rather than unpacking a
free-form dict.

Design notes
------------
* ``frozen=True`` prevents post-routing mutation. Consumers that need to
  override a field (e.g., the chat coordinator rewriting graph_shape to the
  derived execution shape) construct a new RouteDecision via
  ``dataclasses.replace(...)`` rather than mutating in place.

* Validation runs in ``__post_init__`` so invalid enum values fail loudly at
  construction time rather than at consumer-side dict lookup.

* P1 (ADR-0005) removed fields the router emitted but no consumer read.
  ``complexity`` is retained; difficulty is carried by ``thinking_depth``.

* P3 (ADR-0005) adds ``needs_orchestration`` (three-state) so the router can
  ask for pre-planned fanout ("required"), permit in-loop self-escalation via
  the ``agent`` tool ("maybe"), or neither ("none"). It supersedes inferring
  orchestration from ``graph_shape == "plan_fanout"``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ...config.models import ThinkingDepth


PROFILE_VALUES: frozenset[str] = frozenset(
    {"chat", "research", "explore", "coding", "media", "system"}
)
GRAPH_SHAPE_VALUES: frozenset[str] = frozenset(
    {"reply", "tool_loop", "plan_fanout"}
)
COMPLEXITY_VALUES: frozenset[str] = frozenset({"simple", "medium", "large"})
NEEDS_ORCHESTRATION_VALUES: frozenset[str] = frozenset({"none", "maybe", "required"})


@dataclass(slots=True, frozen=True)
class RouteDecision:
    """Strict-typed router LLM output.

    Enum fields are validated in ``__post_init__``. Mutate via
    ``dataclasses.replace(decision, ...)``.
    """

    # === Core routing ===
    profile: Literal["chat", "research", "explore", "coding", "media", "system"]
    graph_shape: Literal["reply", "tool_loop", "plan_fanout"]
    complexity: Literal["simple", "medium", "large"]

    # === Tool routing ===
    tools: list[str] = field(default_factory=list)
    may_write: bool = False

    # === Orchestration routing (ADR-0005 P3) ===
    # none     = single-agent (tools/reply).
    # maybe    = single-agent tool loop that ALSO gets an injected `agent` tool,
    #            so the model can self-escalate to workers mid-loop.
    # required = pre-planned multi-agent fanout (plan_fanout).
    needs_orchestration: Literal["none", "maybe", "required"] = "none"

    # === Execution hints ===
    reasoning: str = ""
    thinking_depth: ThinkingDepth = ThinkingDepth.NONE

    # === Memory routing (rule-derived by apply_memory_guidance) ===
    memory_route: str = "none"

    # === Persona routing (preserved from ContextDecision) ===
    register: str | None = None
    active_trigger_ids: tuple[str, ...] = ()
    situation_strength: str = "ordinary"
    quiet_hour_hints: tuple[str, ...] = ()

    # === Observability ===
    llm_trace: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.profile not in PROFILE_VALUES:
            raise ValueError(
                f"RouteDecision.profile must be one of {sorted(PROFILE_VALUES)}, "
                f"got {self.profile!r}"
            )
        if self.graph_shape not in GRAPH_SHAPE_VALUES:
            raise ValueError(
                f"RouteDecision.graph_shape must be one of {sorted(GRAPH_SHAPE_VALUES)}, "
                f"got {self.graph_shape!r}"
            )
        if self.complexity not in COMPLEXITY_VALUES:
            raise ValueError(
                f"RouteDecision.complexity must be one of {sorted(COMPLEXITY_VALUES)}, "
                f"got {self.complexity!r}"
            )
        if self.needs_orchestration not in NEEDS_ORCHESTRATION_VALUES:
            raise ValueError(
                f"RouteDecision.needs_orchestration must be one of "
                f"{sorted(NEEDS_ORCHESTRATION_VALUES)}, got {self.needs_orchestration!r}"
            )

    def to_legacy_strategy_dict(self) -> dict[str, Any]:
        """Adapter for the Phase B migration window.

        Consumers reading the legacy ``orchestration_strategy: dict``
        (mode / planner / default_leaf_type / allow_parallel) can call
        this method to get a compatible view.
        """
        if self.graph_shape == "plan_fanout":
            mode = "decompose"
        else:
            mode = "direct"
        if self.profile == "coding" or self.may_write:
            default_leaf_type = "Coding"
        elif self.profile == "explore":
            default_leaf_type = "CodeExplore"
        else:
            default_leaf_type = "general-purpose"
        return {
            "mode": mode,
            "planner": "task_agent",
            "default_leaf_type": default_leaf_type,
            "allow_parallel": mode == "decompose",
        }


__all__ = [
    "RouteDecision",
    "PROFILE_VALUES",
    "GRAPH_SHAPE_VALUES",
    "COMPLEXITY_VALUES",
    "NEEDS_ORCHESTRATION_VALUES",
]
