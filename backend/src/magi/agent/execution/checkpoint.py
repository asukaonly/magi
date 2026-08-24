"""Typed checkpoint for resuming a unified agent run at a loop boundary."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .evidence import ToolExecutionEvidence
from .reasoning import ReasoningPolicy, ReasoningState


@dataclass(slots=True)
class AgentRunCheckpoint:
    """Complete model-facing and governance state captured between steps."""

    run_id: str
    messages: list[dict[str, Any]]
    effective_system_prompt: str
    tools: list[dict[str, Any]]
    iteration: int
    reasoning_policy: ReasoningPolicy
    reasoning_state: ReasoningState
    run_plan_id: str | None = None
    run_plan_version: int = 0
    selected_tool_names: list[str] = field(default_factory=list)
    repair_iterations: int = 0
    tool_evidence: list[ToolExecutionEvidence] = field(default_factory=list)
    tool_failures: list[dict[str, Any]] = field(default_factory=list)
    chat_attachments: list[dict[str, Any]] = field(default_factory=list)
    message_payload: dict[str, Any] = field(default_factory=dict)
    tool_expansion_count: int = 0
    consecutive_failed_tool_iterations: int = 0
    all_tools_failed: bool = False
    failed_tool_call_fingerprints: set[str] = field(default_factory=set)
    failure_signature_counts: dict[str, int] = field(default_factory=dict)
    repeated_blocker_tool_names: set[str] = field(default_factory=set)
    suppressed_tool_names: set[str] = field(default_factory=set)
    persona_task_clamp_applied: bool = False
    reason: str = "checkpoint"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "messages": deepcopy(self.messages),
            "effective_system_prompt": self.effective_system_prompt,
            "tools": deepcopy(self.tools),
            "iteration": self.iteration,
            "reasoning_policy": self.reasoning_policy.to_dict(),
            "reasoning_state": self.reasoning_state.to_dict(),
            "run_plan_id": self.run_plan_id,
            "run_plan_version": self.run_plan_version,
            "selected_tool_names": list(self.selected_tool_names),
            "repair_iterations": self.repair_iterations,
            "tool_evidence": [item.to_dict() for item in self.tool_evidence],
            "tool_failures": deepcopy(self.tool_failures),
            "chat_attachments": deepcopy(self.chat_attachments),
            "message_payload": deepcopy(self.message_payload),
            "tool_expansion_count": self.tool_expansion_count,
            "consecutive_failed_tool_iterations": self.consecutive_failed_tool_iterations,
            "all_tools_failed": self.all_tools_failed,
            "failed_tool_call_fingerprints": sorted(self.failed_tool_call_fingerprints),
            "failure_signature_counts": dict(self.failure_signature_counts),
            "repeated_blocker_tool_names": sorted(self.repeated_blocker_tool_names),
            "suppressed_tool_names": sorted(self.suppressed_tool_names),
            "persona_task_clamp_applied": self.persona_task_clamp_applied,
            "reason": self.reason,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentRunCheckpoint":
        return cls(
            run_id=str(value["run_id"]),
            messages=deepcopy(value["messages"]),
            effective_system_prompt=str(value["effective_system_prompt"]),
            tools=deepcopy(value["tools"]),
            iteration=int(value["iteration"]),
            reasoning_policy=ReasoningPolicy.from_dict(dict(value["reasoning_policy"])),
            reasoning_state=ReasoningState.from_dict(dict(value["reasoning_state"])),
            run_plan_id=(
                str(value["run_plan_id"]) if value.get("run_plan_id") is not None else None
            ),
            run_plan_version=int(value.get("run_plan_version") or 0),
            selected_tool_names=[str(item) for item in value["selected_tool_names"]],
            repair_iterations=int(value["repair_iterations"]),
            tool_evidence=[
                ToolExecutionEvidence.from_dict(dict(item)) for item in value["tool_evidence"]
            ],
            tool_failures=deepcopy(value["tool_failures"]),
            chat_attachments=deepcopy(value["chat_attachments"]),
            message_payload=deepcopy(value["message_payload"]),
            tool_expansion_count=int(value["tool_expansion_count"]),
            consecutive_failed_tool_iterations=int(value["consecutive_failed_tool_iterations"]),
            all_tools_failed=bool(value["all_tools_failed"]),
            failed_tool_call_fingerprints=set(value["failed_tool_call_fingerprints"]),
            failure_signature_counts={
                str(key): int(count)
                for key, count in dict(value["failure_signature_counts"]).items()
            },
            repeated_blocker_tool_names=set(value["repeated_blocker_tool_names"]),
            suppressed_tool_names=set(value["suppressed_tool_names"]),
            persona_task_clamp_applied=bool(value["persona_task_clamp_applied"]),
            reason=str(value["reason"]),
            note=str(value["note"]),
        )


__all__ = ["AgentRunCheckpoint"]
