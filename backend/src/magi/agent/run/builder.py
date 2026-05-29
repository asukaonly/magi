"""GraphBuilder: translate RouteDecision into a NodeSpec sequence.

Phase D rule set:
1. Look up the base sequence from GRAPH_TEMPLATES by graph_shape.
2. If profile == "coding" AND the primary node could have touched files
   (graph_shape in {tool_loop, plan_fanout}), append a ValidateNode.

Phase E will extend this with per-profile policy: media → asset
constraint Node, system → trace assert Node, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .spec import GRAPH_TEMPLATES, NodeSpec

if TYPE_CHECKING:
    from ...tools.context_routing import RouteDecision


_CODING_PRIMARY_NODES_THAT_MAY_TOUCH_FILES: frozenset[str] = frozenset(
    {"tool_loop", "plan_fanout"}
)


class GraphBuilder:
    """Stateless builder: ``RouteDecision → list[NodeSpec]``."""

    __slots__ = ()

    def build_node_sequence(self, route_decision: "RouteDecision") -> list[NodeSpec]:
        """Return the ordered Node sequence for ``route_decision``.

        Phase D rules:
          - Base: ``GRAPH_TEMPLATES[graph_shape]``.
          - profile=coding + primary node in {tool_loop, plan_fanout}:
            append ``NodeSpec(node_type="validate")``.

        Raises ``KeyError`` if ``graph_shape`` is not in GRAPH_TEMPLATES
        (an unknown graph_shape from the router is a programmer error
        — RouteDecision's __post_init__ validates the enum).
        """
        base = GRAPH_TEMPLATES[route_decision.graph_shape]
        sequence: list[NodeSpec] = list(base)
        if (
            route_decision.profile == "coding"
            and route_decision.graph_shape in _CODING_PRIMARY_NODES_THAT_MAY_TOUCH_FILES
            and route_decision.may_write
        ):
            sequence.append(NodeSpec(node_type="validate"))
        return sequence


__all__ = ["GraphBuilder"]
