"""Snapshot aggregation for chat execution traces."""

from __future__ import annotations

from typing import Any, Optional

from .models import (
    ExecutionTraceNode,
    ExecutionTraceSnapshot,
    ExecutionTraceSummary,
)

_SEMANTIC_STEP_KINDS = frozenset({"attempt", "skill", "tool", "worker"})
_STEP_STATUS_PRIORITY = {
    "completed": 0,
    "pending": 1,
    "running": 1,
    "failed": 2,
}


class TraceSnapshotBuilderMixin:
    """Builds trace snapshots from normalized runtime trace rows."""

    def _build_runtime_trace_root(
        self,
        *,
        turn: dict[str, Any],
        spans: list[dict[str, Any]],
        llm_calls: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
    ) -> ExecutionTraceNode:
        raise NotImplementedError

    def _ms_to_seconds(self, value: Any) -> Optional[float]:
        raise NotImplementedError

    def _normalize_status(self, status: str) -> str:
        raise NotImplementedError

    def _is_terminal_status(self, status: str) -> bool:
        raise NotImplementedError

    def _optional_text(self, value: Any) -> Optional[str]:
        raise NotImplementedError

    def _safe_int(self, value: Any, *, default: int) -> int:
        raise NotImplementedError

    def _build_snapshot_from_trace_rows(
        self,
        *,
        user_id: str,
        session_id: str,
        turn: dict[str, Any],
        spans: list[dict[str, Any]],
        llm_calls: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
    ) -> Optional[ExecutionTraceSnapshot]:
        turn_id = str(turn.get("turn_id") or "").strip()
        if not turn_id:
            return None
        root = self._build_runtime_trace_root(
            turn=turn,
            spans=spans,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
        )
        mode = self._snapshot_mode(
            turn=turn,
            root=root,
        )
        started_at, ended_at, status = self._apply_turn_status(root=root, turn=turn)
        summary = self._build_trace_summary(
            turn_id=turn_id,
            mode=mode,
            status=status,
            root=root,
            started_at=started_at,
            ended_at=ended_at,
            llm_calls=llm_calls,
            turn=turn,
        )
        return ExecutionTraceSnapshot(
            turn_id=turn_id,
            user_id=user_id,
            session_id=session_id,
            status=status,
            mode=mode,
            started_at=started_at,
            ended_at=root.ended_at,
            continued_from_turn_id=self._optional_text(turn.get("continued_from_turn_id")),
            continued_from_trace_id=self._optional_text(turn.get("continued_from_trace_id")),
            superseded_by_turn_id=self._optional_text(turn.get("superseded_by_turn_id")),
            supersession_reason=self._optional_text(turn.get("supersession_reason")),
            summary=summary,
            root=root,
        )

    def _snapshot_mode(
        self,
        *,
        turn: dict[str, Any],
        root: ExecutionTraceNode,
    ) -> str:
        return str(
            turn.get("mode")
            or self._resolve_normalized_mode(
                root=root,
            )
        )

    def _apply_turn_status(
        self,
        *,
        root: ExecutionTraceNode,
        turn: dict[str, Any],
    ) -> tuple[Optional[float], Optional[float], str]:
        started_at = self._ms_to_seconds(turn.get("started_at_ms"))
        ended_at = self._ms_to_seconds(turn.get("ended_at_ms"))
        status = self._normalize_status(str(turn.get("status") or "running"))
        root.status = status
        root.started_at = root.started_at if root.started_at is not None else started_at
        root.ended_at = ended_at if self._is_terminal_status(status) else None
        return started_at, ended_at, status

    def _trace_token_totals(
        self,
        llm_calls: list[dict[str, Any]],
    ) -> tuple[int, int, int]:
        total_input_tokens = sum(
            self._safe_int(call.get("input_tokens"), default=0) for call in llm_calls
        )
        total_output_tokens = sum(
            self._safe_int(call.get("output_tokens"), default=0) for call in llm_calls
        )
        total_reasoning_tokens = sum(
            self._safe_int(call.get("reasoning_tokens"), default=0) for call in llm_calls
        )
        return total_input_tokens, total_output_tokens, total_reasoning_tokens

    def _build_trace_summary(
        self,
        *,
        turn_id: str,
        mode: str,
        status: str,
        root: ExecutionTraceNode,
        started_at: Optional[float],
        ended_at: Optional[float],
        llm_calls: list[dict[str, Any]],
        turn: dict[str, Any],
    ) -> ExecutionTraceSummary:
        active_steps, completed_steps, failed_steps = self._count_steps(root)
        input_tokens, output_tokens, reasoning_tokens = self._trace_token_totals(llm_calls)
        return ExecutionTraceSummary(
            turn_id=turn_id,
            mode=mode,
            status=status,
            headline=self._build_headline(
                status=status,
                active_steps=active_steps,
                completed_steps=completed_steps,
            ),
            active_steps=active_steps,
            completed_steps=completed_steps,
            failed_steps=failed_steps,
            duration_seconds=round(
                max(0.0, (ended_at or started_at or 0.0) - (started_at or 0.0)),
                3,
            ),
            trace_available=bool(root.children),
            plan_summary=None,
            continued_from_turn_id=self._optional_text(turn.get("continued_from_turn_id")),
            continued_from_trace_id=self._optional_text(turn.get("continued_from_trace_id")),
            superseded_by_turn_id=self._optional_text(turn.get("superseded_by_turn_id")),
            supersession_reason=self._optional_text(turn.get("supersession_reason")),
            total_input_tokens=input_tokens,
            total_output_tokens=output_tokens,
            total_reasoning_tokens=reasoning_tokens,
        )

    def _resolve_normalized_mode(
        self,
        *,
        root: ExecutionTraceNode,
    ) -> str:
        for node in self._walk_nodes(root):
            if node.kind in {"worker", "dispatch"}:
                return "agent_loop"
        return "function_calling"

    def _count_steps(self, root: ExecutionTraceNode) -> tuple[int, int, int]:
        semantic_steps: dict[str, str] = {}
        for node in self._walk_nodes(root):
            if node.kind not in _SEMANTIC_STEP_KINDS:
                continue
            identity = self._semantic_step_identity(node)
            status = self._normalize_status(node.status)
            previous = semantic_steps.get(identity)
            if previous is None or _STEP_STATUS_PRIORITY.get(
                status, 0
            ) > _STEP_STATUS_PRIORITY.get(previous, 0):
                semantic_steps[identity] = status

        active = sum(status in {"running", "pending"} for status in semantic_steps.values())
        failed = sum(status == "failed" for status in semantic_steps.values())
        completed = len(semantic_steps) - active - failed
        return int(active), int(completed), int(failed)

    @staticmethod
    def _semantic_step_identity(node: ExecutionTraceNode) -> str:
        if node.kind == "tool":
            tool_call_id = str(node.metadata.get("tool_call_id") or "").strip()
            if tool_call_id:
                return f"tool:{tool_call_id}"
        return f"{node.kind}:{node.id}"

    def _build_headline(
        self,
        *,
        status: str,
        active_steps: int,
        completed_steps: int,
    ) -> str:
        if status == "completed":
            return "Tool chain completed"
        if status == "failed":
            return "Tool chain failed"
        if active_steps > 0 or completed_steps > 0:
            return "Running tool chain"
        return "Thinking"

    def _walk_nodes(self, node: ExecutionTraceNode) -> list[ExecutionTraceNode]:
        nodes = [node]
        for child in node.children:
            nodes.extend(self._walk_nodes(child))
        return nodes


__all__ = ["TraceSnapshotBuilderMixin"]
