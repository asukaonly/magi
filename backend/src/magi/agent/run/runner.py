"""NodeSequenceRunner: execute a list of NodeSpecs in order.

Phase D scope: simple sequential execution. On any node returning
FAILED, the runner stops and returns a failure-surfaced result. On
all-DONE, the runner merges per-node ExecutionResult.response_text
with newline separators and returns the combined result.

Phase E will introduce a real AgentRunKernel that handles fanout,
child runs, snapshot/detach, and shared state passed between nodes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .nodes.protocol import NodeOutcome
from .registry import NodeRegistry
from .spec import NodeSpec

if TYPE_CHECKING:
    from ..task_agents.common.contracts import ExecutionMode, ExecutionRequest, ExecutionResult


class NodeSequenceRunner:
    """Execute a list of NodeSpecs in order against one request.

    Sequential execution semantics:
    - DONE outcomes are accumulated; per-node response_text is merged
      into the final result with newline separators.
    - FAILED short-circuits: subsequent nodes do not run. The returned
      ExecutionResult surfaces both whatever accumulated successfully
      AND the failure message.
    - An unregistered node_type raises ValueError loudly (programmer error).
    """

    __slots__ = ("_node_registry",)

    def __init__(self, *, node_registry: NodeRegistry) -> None:
        self._node_registry = node_registry

    async def run(
        self,
        *,
        node_specs: list[NodeSpec],
        request: "ExecutionRequest",
    ) -> "ExecutionResult | None":
        if not node_specs:
            return None

        accumulated_texts: list[str] = []
        primary_result: ExecutionResult | None = None

        for spec in node_specs:
            node = self._node_registry.get(spec.node_type)
            if node is None:
                raise ValueError(
                    f"NodeSequenceRunner.run: no Node registered for node_type "
                    f"{spec.node_type!r}"
                )

            node_result = await node.execute(request)

            if node_result.execution_result is not None:
                if primary_result is None:
                    primary_result = node_result.execution_result
                if node_result.execution_result.response_text:
                    accumulated_texts.append(
                        node_result.execution_result.response_text
                    )

            if node_result.outcome == NodeOutcome.FAILED:
                error_text = node_result.error or "Node failed"
                accumulated_texts.append(f"[error] {error_text}")
                return _merge_accumulated_into_result(
                    primary_result=primary_result,
                    accumulated_texts=accumulated_texts,
                )

        return _merge_accumulated_into_result(
            primary_result=primary_result,
            accumulated_texts=accumulated_texts,
        )


def _merge_accumulated_into_result(
    *,
    primary_result: "ExecutionResult | None",
    accumulated_texts: list[str],
) -> "ExecutionResult":
    """Combine accumulated response texts into a single ExecutionResult.

    Uses the primary node's ExecutionResult as the carrier (preserves
    its non-text fields like attachments, ux_plan, message_payload).
    The text fields from every node are joined with double-newlines.
    """
    # Lazy import to avoid circular dependency via task_agents.__init__
    from ..task_agents.common.contracts import ExecutionMode, ExecutionResult  # noqa: PLC0415

    combined_text = "\n\n".join(t for t in accumulated_texts if t).strip()
    if primary_result is None:
        # No node produced an ExecutionResult; build a minimal one to
        # carry the combined text. This is rare — only reached when
        # every node returned NodeResult with execution_result=None.
        return ExecutionResult(
            mode=ExecutionMode.DIRECT_LLM,
            response_text=combined_text or "(no output)",
        )

    # Frozen dataclasses can be replaced via dataclasses.replace; but
    # ExecutionResult is mutable (slots=True without frozen), so direct
    # field assignment is fine. Verify by reading the contracts.py
    # definition — ExecutionResult uses @dataclass(slots=True), not frozen.
    primary_result.response_text = combined_text
    return primary_result


__all__ = ["NodeSequenceRunner"]
