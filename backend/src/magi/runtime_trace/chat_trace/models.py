"""UI-facing execution trace DTOs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class ExecutionTraceNode:
    """One node in the UI-facing execution trace tree."""

    id: str
    kind: str
    label: str
    status: str
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    result_preview: str = ""
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    children: list["ExecutionTraceNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "result_preview": self.result_preview,
            "error": self.error,
            "metadata": dict(self.metadata),
            "children": [child.to_dict() for child in self.children],
        }


@dataclass(slots=True)
class ExecutionTraceSummary:
    """Compact summary used by chat status cards and assistant chips."""

    turn_id: str
    mode: str
    status: str
    headline: str
    active_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    duration_seconds: float = 0.0
    trace_available: bool = False
    plan_summary: Optional["ExecutionPlanSummary"] = None
    continued_from_turn_id: Optional[str] = None
    continued_from_trace_id: Optional[str] = None
    superseded_by_turn_id: Optional[str] = None
    supersession_reason: Optional[str] = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_reasoning_tokens: int = 0
    runtime_metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "mode": self.mode,
            "status": self.status,
            "headline": self.headline,
            "active_steps": self.active_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "duration_seconds": self.duration_seconds,
            "trace_available": self.trace_available,
            "plan_summary": self.plan_summary.to_dict() if self.plan_summary is not None else None,
            "continued_from_turn_id": self.continued_from_turn_id,
            "continued_from_trace_id": self.continued_from_trace_id,
            "superseded_by_turn_id": self.superseded_by_turn_id,
            "supersession_reason": self.supersession_reason,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_reasoning_tokens": self.total_reasoning_tokens,
            "runtime_metrics": dict(self.runtime_metrics),
        }


@dataclass(slots=True)
class ExecutionPlanStepSummary:
    """Compact step preview for orchestration summaries."""

    subtask_id: Optional[str]
    label: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "subtask_id": self.subtask_id,
            "label": self.label,
            "status": self.status,
        }


@dataclass(slots=True)
class ExecutionPlanSummary:
    """Preview payload used by the chat execution card."""

    planner: Optional[str]
    parallel_mode: str
    total_steps: int
    remaining_steps: int
    steps: list[ExecutionPlanStepSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "planner": self.planner,
            "parallel_mode": self.parallel_mode,
            "total_steps": self.total_steps,
            "remaining_steps": self.remaining_steps,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(slots=True)
class ExecutionTraceSnapshot:
    """Full turn snapshot returned to the frontend drawer."""

    turn_id: str
    user_id: str
    session_id: str
    status: str
    mode: str
    started_at: Optional[float]
    ended_at: Optional[float]
    continued_from_turn_id: Optional[str]
    continued_from_trace_id: Optional[str]
    superseded_by_turn_id: Optional[str]
    supersession_reason: Optional[str]
    summary: ExecutionTraceSummary
    root: ExecutionTraceNode

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "status": self.status,
            "mode": self.mode,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "continued_from_turn_id": self.continued_from_turn_id,
            "continued_from_trace_id": self.continued_from_trace_id,
            "superseded_by_turn_id": self.superseded_by_turn_id,
            "supersession_reason": self.supersession_reason,
            "summary": self.summary.to_dict(),
            "root": self.root.to_dict(),
        }
