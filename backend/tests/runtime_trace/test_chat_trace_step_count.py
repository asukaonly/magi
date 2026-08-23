"""Tests for semantic execution-step summary counts."""

from magi.runtime_trace.chat_trace.models import ExecutionTraceNode
from magi.runtime_trace.chat_trace.snapshot_builder import TraceSnapshotBuilderMixin


class _Builder(TraceSnapshotBuilderMixin):
    def _normalize_status(self, status: str) -> str:
        return status

    def _walk_nodes(self, root: ExecutionTraceNode):
        yield root
        for child in root.children:
            yield from self._walk_nodes(child)


def _node(
    node_id: str,
    kind: str,
    status: str = "completed",
    *,
    children: list[ExecutionTraceNode] | None = None,
    tool_call_id: str | None = None,
) -> ExecutionTraceNode:
    return ExecutionTraceNode(
        id=node_id,
        kind=kind,
        label=node_id,
        status=status,
        metadata={"tool_call_id": tool_call_id} if tool_call_id else {},
        children=children or [],
    )


def test_count_steps_uses_semantic_actions_only() -> None:
    tool_invocation = _node(
        "invoke-1",
        "tool_invocation",
        tool_call_id="call-1",
    )
    root = _node(
        "root",
        "root",
        children=[
            _node("intent", "intent"),
            _node("llm", "llm"),
            _node(
                "tool-1",
                "tool",
                children=[tool_invocation],
                tool_call_id="call-1",
            ),
            _node("attempt-1", "attempt", "failed"),
            _node("skill-1", "skill", "running"),
            _node("response", "response"),
        ],
    )

    assert _Builder()._count_steps(root) == (1, 1, 1)


def test_count_steps_deduplicates_semantic_tool_call_rows() -> None:
    root = _node(
        "root",
        "root",
        children=[
            _node("tool-1", "tool", tool_call_id="call-1"),
            _node("tool-1-copy", "tool", tool_call_id="call-1"),
        ],
    )

    assert _Builder()._count_steps(root) == (0, 1, 0)
