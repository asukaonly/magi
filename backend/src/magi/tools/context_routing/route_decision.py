"""RouteDecision: strict typed schema for the chat router LLM output.

The router LLM emits a JSON object matching this schema; downstream
consumers receive a typed ``RouteDecision`` rather than unpacking a
free-form dict.

Design notes
------------
* ``frozen=True`` prevents post-routing mutation. Mutate via
  ``dataclasses.replace(...)``.

* Validation runs in ``__post_init__``.

* P1 (ADR-0005) removed dead fields; ``complexity`` is retained.

* P3 (ADR-0005) added the three-state ``needs_orchestration``.

    * Persona-routing fields are grouped under a nested ``persona``
      (:class:`PersonaRouting`) sub-object so persona routing can be split out
      of the router later without touching the rest of RouteDecision. Flat
      ``@property`` accessors (``register`` etc.) are kept as a transition shim so
      existing readers keep working; they can be dropped once persona routing is
      fully extracted.
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
TOOL_NEED_VALUES: frozenset[str] = frozenset({"none", "direct", "discover"})


@dataclass(slots=True, frozen=True)
class PersonaRouting:
    """Persona-routing fields produced by the router LLM, grouped (ADR-0005).

    Isolated into its own object so persona routing can be extracted from the
    router later as a unit.
    """

    register: str | None = None
    active_trigger_ids: tuple[str, ...] = ()
    situation_strength: str = "ordinary"
    quiet_hour_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
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
    # none     = ordinary no-tool reply.
    # direct   = the router selected concrete capability tools in ``tools``.
    # discover = tool-assisted turn, but exact capability should be found by
    #            the main model via the routed find-relevant-tools entry.
    tool_need: Literal["none", "direct", "discover"] = "none"
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

    # === Persona routing (grouped sub-object; ADR-0005) ===
    persona: PersonaRouting = field(default_factory=PersonaRouting)

    # === Observability ===
    llm_trace: dict[str, Any] = field(default_factory=dict)

    # --- Backward-compatible flat accessors (transition shim) ---
    # Persona fields now live under ``persona``; these proxies keep existing
    # readers (``_build_persona_routing_hint``, tests) working unchanged.
    @property
    def register(self) -> str | None:
        return self.persona.register

    @property
    def active_trigger_ids(self) -> tuple[str, ...]:
        return self.persona.active_trigger_ids

    @property
    def situation_strength(self) -> str:
        return self.persona.situation_strength

    @property
    def quiet_hour_hints(self) -> tuple[str, ...]:
        return self.persona.quiet_hour_hints

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
        if self.tool_need not in TOOL_NEED_VALUES:
            raise ValueError(
                f"RouteDecision.tool_need must be one of {sorted(TOOL_NEED_VALUES)}, "
                f"got {self.tool_need!r}"
            )

    @property
    def orchestration_mode(self) -> Literal["direct", "decompose"]:
        if self.graph_shape == "plan_fanout":
            return "decompose"
        return "direct"

    @property
    def orchestration_planner(self) -> str:
        return "task_agent"

    @property
    def default_leaf_type(self) -> str:
        if self.profile == "coding" or self.may_write:
            return "Coding"
        if self.profile == "explore":
            return "CodeExplore"
        return "general-purpose"

    @property
    def allow_parallel(self) -> bool:
        return self.orchestration_mode == "decompose"


__all__ = [
    "RouteDecision",
    "PersonaRouting",
    "PROFILE_VALUES",
    "GRAPH_SHAPE_VALUES",
    "COMPLEXITY_VALUES",
    "NEEDS_ORCHESTRATION_VALUES",
    "TOOL_NEED_VALUES",
]
