"""RunNode protocol + NodeResult dataclass for Phase C–E run-kernel adapters.

Design notes
------------
* Phase C: nodes are thin adapters around existing handlers
  (DirectLLMHandler, FunctionCallingHandler, OrchestrationLaunchHandler).
  ``execute(request: ExecutionRequest) -> NodeResult`` is the shape.
  Phase E will replace the input with a richer ``RunContext`` carrying
  ``AgentRun`` state.

* ``NodeOutcome`` is intentionally tiny in Phase C — only ``DONE``
  (terminal, the wrapped handler produced a final ExecutionResult),
  ``NEXT`` (reserved for Phase D multi-node graphs), and ``FAILED``
  (terminal error). Phase D adds ``WAIT_CHILDREN`` for the plan_fanout
  pause-and-resume case.

* ``NodeResult`` is frozen so consumers cannot mutate a returned
  outcome. When the wrapped handler returns an ``ExecutionResult``, it
  is carried through unchanged on ``NodeResult.execution_result``.

* ``RunNode`` is a ``runtime_checkable`` Protocol so the
  ``NodeRegistry`` can validate adapter conformance at registration
  time. The Protocol declares ``execute`` plus a class-level
  ``node_type`` discriminator string used by the registry's
  graph_shape → node lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ...task_agents.common.contracts import ExecutionRequest, ExecutionResult


class NodeOutcome(str, Enum):
    """Result kind for a Node.execute() call.

    Phase C uses only DONE / FAILED for the adapter pattern. NEXT is
    reserved for Phase D when ValidateNode auto-appends after a coding
    ToolLoopNode and the node sequence needs explicit advance signals.
    """

    DONE = "done"
    NEXT = "next"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class NodeResult:
    """Frozen result returned from a Node.execute() call.

    ``execution_result`` is populated by Phase C adapters that wrap the
    legacy ``ExecutionHandler`` chain. The chat coordinator consumes it
    via the existing ``parse_result`` postprocess path.

    ``error`` carries a human-readable failure message when
    ``outcome == FAILED``.
    """

    outcome: NodeOutcome
    execution_result: "ExecutionResult | None" = None
    error: str | None = None


@runtime_checkable
class RunNode(Protocol):
    """Phase C adapter protocol; Phase E adds snapshot/restore.

    Conformers expose:
      - ``node_type``: class-level discriminator string matching the
        graph_shape value the registry routes to (``"reply"``,
        ``"tool_loop"``, ``"plan_fanout"``).
      - ``execute(request)``: async, takes the existing ExecutionRequest
        shape and returns a NodeResult.
      - ``snapshot()``: return a JSON-compatible dict of this node's state
        for resume after detach. Phase C/D adapters return ``{}`` (stateless).
        ``ToolLoopNode`` overrides to delegate to OrchestratorSnapshot.
      - ``restore(state)``: accept the dict produced by ``snapshot()`` and
        restore the node's internal state. No-op for stateless nodes.
    """

    node_type: str

    async def execute(self, request: "ExecutionRequest") -> NodeResult:
        """Run this node against the request, returning a NodeResult."""
        ...

    def snapshot(self) -> dict[str, Any]:
        """Return JSON-compatible state for resume. Empty dict for stateless nodes."""
        ...

    def restore(self, state: dict[str, Any]) -> None:
        """Restore from a snapshot dict. No-op for stateless nodes."""
        ...


__all__ = ["NodeOutcome", "NodeResult", "RunNode"]
