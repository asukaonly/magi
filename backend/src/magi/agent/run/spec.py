"""NodeSpec dataclass + GRAPH_TEMPLATES constants for Phase D.

Phase D scope: NodeSpec is a frozen, near-empty descriptor carrying
only ``node_type``. Phase E will extend it with per-node config
(timeout, retry policy, etc.).

GRAPH_TEMPLATES is the canonical mapping from RouteDecision.graph_shape
to a tuple of NodeSpecs representing the base sequence for that shape.
Profile-specific appenders (e.g., ValidateNode after ToolLoopNode for
coding) are applied by ``GraphBuilder.build_node_sequence`` rather than
baked into the template, so the template stays small and predictable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NodeSpec:
    """Frozen descriptor for one Node in a sequence.

    ``node_type`` matches the ``RunNode.node_type`` discriminator used
    by ``NodeRegistry.get(...)``.
    """

    node_type: str


GRAPH_TEMPLATES: dict[str, tuple[NodeSpec, ...]] = {
    "reply": (NodeSpec(node_type="reply"),),
    "tool_loop": (NodeSpec(node_type="tool_loop"),),
    "plan_fanout": (NodeSpec(node_type="plan_fanout"),),
}


__all__ = ["NodeSpec", "GRAPH_TEMPLATES"]
