"""RouteDecision: strict typed schema for the chat router LLM output.

Replaces ``ContextDecision`` + ``OrchestrationPlan`` + the keyword
normalization in ``orchestration.py``. The router LLM emits a JSON
object matching this schema; downstream consumers receive a typed
``RouteDecision`` rather than unpacking a free-form dict.

Design notes
------------
* This is a SUPERSET of the design-doc spec. In addition to the
  spec-required fields (``profile``, ``graph_shape``, ``complexity``,
  etc.), the dataclass carries persona-routing + memory-routing fields
  that previously lived on ``ContextDecision``. Those fields are
  produced by the same LLM call; removing them would require
  re-architecting persona routing, which is out of Phase B scope.

* ``frozen=True`` prevents post-routing mutation. Consumers that need
  to override a field (e.g., the chat coordinator suppressing tools
  when image attachments are present) construct a new RouteDecision via
  ``dataclasses.replace(...)`` rather than mutating in place.

* Validation runs in ``__post_init__`` so invalid values fail loudly at
  construction time rather than at consumer-side dict lookup.

* The ``to_legacy_strategy_dict()`` adapter exists ONLY for the Phase B
  migration window — once every consumer has migrated to read
  ``RouteDecision`` directly, this method is deleted in Phase C.
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
BACKGROUND_HINT_VALUES: frozenset[str] = frozenset(
    {"foreground", "background_ok", "background_preferred"}
)
EFFORT_VALUES: frozenset[str] = frozenset(
    {"none", "low", "medium", "high", "max"}
)


@dataclass(slots=True, frozen=True)
class RouteDecision:
    """Strict-typed router LLM output.

    All fields are validated in ``__post_init__``. Construct directly
    or via ``RouteDecision.parse_llm_json(...)`` (defined in the
    parser module). Mutate via ``dataclasses.replace(decision, ...)``.
    """

    # === Core routing (design-doc spec) ===
    profile: Literal["chat", "research", "explore", "coding", "media", "system"]
    graph_shape: Literal["reply", "tool_loop", "plan_fanout"]
    complexity: Literal["simple", "medium", "large"]

    # === Tool routing ===
    tools: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    risky_tools: list[str] = field(default_factory=list)
    needs_workspace: bool = False
    needs_external: bool = False
    may_write: bool = False

    # === Execution hints ===
    background_hint: Literal["foreground", "background_ok", "background_preferred"] = "foreground"
    effort: Literal["none", "low", "medium", "high", "max"] = "low"
    confidence: float = 0.0
    reasoning: str = ""
    thinking_depth: ThinkingDepth = ThinkingDepth.NONE

    # === Memory routing (preserved from ContextDecision) ===
    memory_route: str = "none"
    memory_layer: str | None = None

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
        if self.background_hint not in BACKGROUND_HINT_VALUES:
            raise ValueError(
                f"RouteDecision.background_hint must be one of {sorted(BACKGROUND_HINT_VALUES)}, "
                f"got {self.background_hint!r}"
            )
        if self.effort not in EFFORT_VALUES:
            raise ValueError(
                f"RouteDecision.effort must be one of {sorted(EFFORT_VALUES)}, "
                f"got {self.effort!r}"
            )

    def to_legacy_strategy_dict(self) -> dict[str, Any]:
        """Adapter for the Phase B migration window.

        Consumers reading the legacy ``orchestration_strategy: dict``
        (mode / planner / default_leaf_type / allow_parallel) can call
        this method to get a compatible view. Deleted in Task 11 after
        every consumer migrates.
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
    "BACKGROUND_HINT_VALUES",
    "EFFORT_VALUES",
]
