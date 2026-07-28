"""NodeSequenceRunner: execute a list of NodeSpecs in order.

Phase D scope: simple sequential execution. On any node returning
FAILED, the runner stops and returns a failure-surfaced result. On
all-DONE, the runner merges per-node ExecutionResult.response_text
with newline separators and returns the combined result.

Phase E: ``run_with_snapshot`` is the canonical entry point. It
returns both the merged ExecutionResult AND a RunSnapshot capturing
per-node state. ``run`` is kept as a Phase D-compatible wrapper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .nodes.protocol import NodeOutcome
from .registry import NodeRegistry
from .snapshot import RunSnapshot
from .spec import NodeSpec

if TYPE_CHECKING:
    from ..task_agents.common.contracts import ExecutionRequest, ExecutionResult


class NodeSequenceRunner:
    """Execute a list of NodeSpecs in order against one request.

    Phase E: ``run_with_snapshot`` is the canonical entry point. It
    returns both the merged ExecutionResult AND a RunSnapshot capturing
    per-node state. ``run`` is kept as a Phase D-compatible wrapper.

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
        """Phase D-compatible: returns just the ExecutionResult."""
        result, _snapshot = await self.run_with_snapshot(
            run_id="",
            node_specs=node_specs,
            request=request,
            resume_from=None,
        )
        return result

    async def run_with_snapshot(
        self,
        *,
        run_id: str,
        node_specs: list[NodeSpec],
        request: "ExecutionRequest",
        resume_from: RunSnapshot | None = None,
    ) -> "tuple[ExecutionResult | None, RunSnapshot]":
        """Phase E entry point: returns (ExecutionResult, RunSnapshot).

        ``resume_from``: if supplied, the runner restores each completed
        node's state (indices 0..cursor-1) then jumps to ``resume_from.cursor``
        and continues. The node at ``cursor`` runs from scratch — its
        ``restore()`` is NOT called, so retry semantics work cleanly (a failed
        node resumes from its natural initial state, not from corrupted
        in-flight state).
        """
        graph = _node_graph(node_specs)
        node_states = _resume_node_states(resume_from)
        cursor = _resume_cursor(resume_from)
        self._restore_completed_nodes(
            node_specs=node_specs,
            cursor=cursor,
            node_states=node_states,
        )

        if not node_specs:
            return None, _build_snapshot(
                run_id=run_id,
                graph=graph,
                cursor=0,
                node_states=node_states,
            )

        return await self._run_remaining_nodes(
            run_id=run_id,
            node_specs=node_specs,
            request=request,
            graph=graph,
            node_states=node_states,
            cursor=cursor,
        )

    def _restore_completed_nodes(
        self,
        *,
        node_specs: list[NodeSpec],
        cursor: int,
        node_states: dict[str, dict[str, Any]],
    ) -> None:
        # Nodes before cursor already ran; restore their captured state so
        # they reflect their final condition. The cursor node runs from scratch.
        for i in range(cursor):
            prior_spec = node_specs[i]
            prior_node = self._node_registry.get(prior_spec.node_type)
            if prior_node is not None:
                preserved = node_states.get(prior_spec.node_type, {})
                prior_node.restore(preserved)

    async def _run_remaining_nodes(
        self,
        *,
        run_id: str,
        node_specs: list[NodeSpec],
        request: "ExecutionRequest",
        graph: tuple[str, ...],
        node_states: dict[str, dict[str, Any]],
        cursor: int,
    ) -> "tuple[ExecutionResult | None, RunSnapshot]":
        accumulated_texts: list[str] = []
        primary_result: "ExecutionResult | None" = None

        for idx in range(cursor, len(node_specs)):
            spec = node_specs[idx]
            node = self._node_registry.get(spec.node_type)
            if node is None:
                raise ValueError(
                    f"NodeSequenceRunner.run_with_snapshot: no Node registered for "
                    f"node_type {spec.node_type!r}"
                )

            node_result = await node.execute(request)
            node_states[spec.node_type] = _capture_node_snapshot(node)

            if node_result.execution_result is not None:
                if primary_result is None:
                    primary_result = node_result.execution_result
                if node_result.execution_result.response_text:
                    accumulated_texts.append(node_result.execution_result.response_text)

            if node_result.outcome == NodeOutcome.FAILED:
                error_text = node_result.error or "Node failed"
                accumulated_texts.append(f"[error] {error_text}")
                # Cursor stays at idx (failed node retained for retry).
                snapshot = _build_snapshot(
                    run_id=run_id,
                    graph=graph,
                    cursor=idx,
                    node_states=node_states,
                )
                return (
                    _merge_accumulated_into_result(
                        primary_result=primary_result,
                        accumulated_texts=accumulated_texts,
                    ),
                    snapshot,
                )

        # All nodes completed: cursor advances past the last index.
        snapshot = _build_snapshot(
            run_id=run_id,
            graph=graph,
            cursor=len(node_specs),
            node_states=node_states,
        )
        return (
            _merge_accumulated_into_result(
                primary_result=primary_result,
                accumulated_texts=accumulated_texts,
            ),
            snapshot,
        )


def _node_graph(node_specs: list[NodeSpec]) -> tuple[str, ...]:
    return tuple(spec.node_type for spec in node_specs)


def _resume_node_states(resume_from: RunSnapshot | None) -> dict[str, dict[str, Any]]:
    return dict(resume_from.node_states if resume_from is not None else {})


def _resume_cursor(resume_from: RunSnapshot | None) -> int:
    return resume_from.cursor if resume_from is not None else 0


def _capture_node_snapshot(node: Any) -> dict[str, Any]:
    try:
        return node.snapshot()
    except Exception:
        # Snapshot failures must not break the run; record empty state.
        return {}


def _build_snapshot(
    *,
    run_id: str,
    graph: tuple[str, ...],
    cursor: int,
    node_states: dict[str, dict[str, Any]],
) -> RunSnapshot:
    return RunSnapshot(
        run_id=run_id,
        graph=graph,
        cursor=cursor,
        node_states=node_states,
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
