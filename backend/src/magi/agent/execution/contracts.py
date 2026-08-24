"""Durable contracts for the unified agent run lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentRunEventType(str, Enum):
    """Stable event names persisted by the agent runtime."""

    RUN_STARTED = "run_started"
    RUN_RESUMED = "run_resumed"
    CONTEXT_PREPARED = "context_prepared"
    STEP_STARTED = "step_started"
    REASONING_POLICY_RESOLVED = "reasoning_policy_resolved"
    REASONING_DEPTH_CHANGED = "reasoning_depth_changed"
    MODEL_OUTPUT = "model_output"
    TOOL_CALL_REQUESTED = "tool_call_requested"
    TOOL_EFFECT_ADMITTED = "tool_effect_admitted"
    TOOL_RESULT = "tool_result"
    CHILD_STARTED = "child_started"
    CHILD_COMPLETED = "child_completed"
    CHILD_CANCELLED = "child_cancelled"
    CAPABILITIES_RESOLVED = "capabilities_resolved"
    CAPABILITIES_EXPANDED = "capabilities_expanded"
    ATTACHMENT_OBSERVED = "attachment_observed"
    CONTROL_RECEIVED = "control_received"
    PLAN_UPDATED = "plan_updated"
    VALIDATION_COMPLETED = "validation_completed"
    COMPLETION_REQUESTED = "completion_requested"
    COMPLETION_REJECTED = "completion_rejected"
    REPAIR_STARTED = "repair_started"
    REPAIR_STEP_STARTED = "repair_step_started"
    REPAIR_EXHAUSTED = "repair_exhausted"
    RUN_SUSPENDED = "run_suspended"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


class CompletionOutcome(str, Enum):
    """Runtime action after evaluating a proposed final response."""

    COMPLETE = "complete"
    CONTINUE = "continue"
    SUSPEND = "suspend"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Privacy-minimized reference to evidence produced during one run."""

    evidence_id: str
    kind: str
    source: str
    status: str
    payload_digest: str
    created_at_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "source": self.source,
            "status": self.status,
            "payload_digest": self.payload_digest,
            "created_at_ms": self.created_at_ms,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RunContextManifest:
    """The exact effective context used to start a new model-facing run."""

    run_id: str
    turn_id: str | None
    session_id: str | None
    user_id: str | None
    prompt_assembly_version: str
    system_prompt_hash: str
    messages: tuple[dict[str, Any], ...]
    tool_catalog: tuple[str, ...]
    tool_schemas: tuple[dict[str, Any], ...]
    tool_schema_hashes: dict[str, str]
    context_sources: tuple[dict[str, Any], ...] = ()
    provider: str | None = None
    model: str | None = None
    reasoning_policy: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "prompt_assembly_version": self.prompt_assembly_version,
            "system_prompt_hash": self.system_prompt_hash,
            "messages": [dict(item) for item in self.messages],
            "tool_catalog": list(self.tool_catalog),
            "tool_schemas": [dict(item) for item in self.tool_schemas],
            "tool_schema_hashes": dict(self.tool_schema_hashes),
            "context_sources": [dict(item) for item in self.context_sources],
            "provider": self.provider,
            "model": self.model,
            "reasoning_policy": dict(self.reasoning_policy),
            "created_at_ms": self.created_at_ms,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RunContextManifest":
        return cls(
            run_id=str(value["run_id"]),
            turn_id=_optional_text(value.get("turn_id")),
            session_id=_optional_text(value.get("session_id")),
            user_id=_optional_text(value.get("user_id")),
            prompt_assembly_version=str(value.get("prompt_assembly_version") or "unknown"),
            system_prompt_hash=str(value.get("system_prompt_hash") or ""),
            messages=tuple(
                dict(item)
                for item in value.get("messages", [])
                if isinstance(item, dict)
            ),
            tool_catalog=tuple(str(item) for item in value.get("tool_catalog", []) if item),
            tool_schemas=tuple(
                dict(item)
                for item in value.get("tool_schemas", [])
                if isinstance(item, dict)
            ),
            tool_schema_hashes={
                str(key): str(item)
                for key, item in dict(value.get("tool_schema_hashes") or {}).items()
            },
            context_sources=tuple(
                dict(item)
                for item in value.get("context_sources", [])
                if isinstance(item, dict)
            ),
            provider=_optional_text(value.get("provider")),
            model=_optional_text(value.get("model")),
            reasoning_policy=dict(value.get("reasoning_policy") or {}),
            created_at_ms=int(value.get("created_at_ms") or 0),
        )


@dataclass(frozen=True, slots=True)
class AgentRunEvent:
    """One append-only event in the canonical run journal."""

    event_id: str
    run_id: str
    sequence: int
    event_type: AgentRunEventType
    created_at_ms: int
    turn_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    step_index: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "created_at_ms": self.created_at_ms,
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "step_index": self.step_index,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentRunEvent":
        return cls(
            event_id=str(value["event_id"]),
            run_id=str(value["run_id"]),
            sequence=int(value["sequence"]),
            event_type=AgentRunEventType(str(value["event_type"])),
            created_at_ms=int(value["created_at_ms"]),
            turn_id=_optional_text(value.get("turn_id")),
            session_id=_optional_text(value.get("session_id")),
            user_id=_optional_text(value.get("user_id")),
            step_index=(
                int(value["step_index"])
                if value.get("step_index") is not None
                else None
            ),
            payload=dict(value.get("payload") or {}),
        )


@dataclass(frozen=True, slots=True)
class CompletionDecision:
    """Structured completion result owned by the runtime."""

    outcome: CompletionOutcome
    reason_code: str
    observations: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    repairable: bool = False
    reasoning_helpful: bool = False
    suggested_reasoning_floor: str | None = None

    @property
    def complete(self) -> bool:
        return self.outcome is CompletionOutcome.COMPLETE

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "observations": list(self.observations),
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "repairable": self.repairable,
            "reasoning_helpful": self.reasoning_helpful,
            "suggested_reasoning_floor": self.suggested_reasoning_floor,
        }


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = [
    "AgentRunEvent",
    "AgentRunEventType",
    "CompletionDecision",
    "CompletionOutcome",
    "EvidenceRef",
    "RunContextManifest",
]
