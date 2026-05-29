"""NodeRegistry: graph_shape → RunNode lookup."""

from __future__ import annotations

from .nodes.protocol import RunNode


class NodeRegistry:
    """In-memory ``graph_shape → RunNode`` registry."""

    __slots__ = ("_nodes",)

    def __init__(self) -> None:
        self._nodes: dict[str, RunNode] = {}

    def register(self, node: RunNode) -> None:
        """Register ``node`` under its ``node_type`` key.

        Raises ``TypeError`` if ``node`` does not conform to ``RunNode``.
        Raises ``ValueError`` if ``node_type`` already registered.
        """
        if not isinstance(node, RunNode):
            raise TypeError(
                f"NodeRegistry.register: object does not conform to RunNode "
                f"(missing 'execute' or 'node_type'): {node!r}"
            )
        key = node.node_type
        if key in self._nodes:
            raise ValueError(
                f"NodeRegistry.register: graph_shape {key!r} is already "
                f"registered to {self._nodes[key]!r}"
            )
        self._nodes[key] = node

    def get(self, graph_shape: str) -> RunNode | None:
        """Return the registered Node for ``graph_shape``, or ``None``."""
        return self._nodes.get(graph_shape)

    def graph_shapes(self) -> list[str]:
        """Diagnostic: return the registered graph_shape keys."""
        return list(self._nodes.keys())


__all__ = ["NodeRegistry"]
