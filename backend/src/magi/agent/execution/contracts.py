"""Durable contracts for the unified agent run lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CompletionOutcome(str, Enum):
    """Runtime action after evaluating a proposed final response."""

    COMPLETE = "complete"
    CONTINUE = "continue"
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
    """Privacy-minimized provenance for a new model-facing run."""

    run_id: str
    turn_id: str | None
    session_id: str | None
    user_id: str | None
    prompt_assembly_version: str
    system_prompt_hash: str
    system_prompt_size_bytes: int
    message_fingerprints: tuple[dict[str, Any], ...]
    tool_catalog: tuple[str, ...]
    tool_schema_hashes: dict[str, str]
    context_source_refs: tuple[dict[str, Any], ...] = ()
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
            "system_prompt_size_bytes": self.system_prompt_size_bytes,
            "message_fingerprints": [dict(item) for item in self.message_fingerprints],
            "tool_catalog": list(self.tool_catalog),
            "tool_schema_hashes": dict(self.tool_schema_hashes),
            "context_source_refs": [dict(item) for item in self.context_source_refs],
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
            system_prompt_size_bytes=int(value.get("system_prompt_size_bytes") or 0),
            message_fingerprints=tuple(
                dict(item)
                for item in value.get("message_fingerprints", [])
                if isinstance(item, dict)
            ),
            tool_catalog=tuple(str(item) for item in value.get("tool_catalog", []) if item),
            tool_schema_hashes={
                str(key): str(item)
                for key, item in dict(value.get("tool_schema_hashes") or {}).items()
            },
            context_source_refs=tuple(
                dict(item)
                for item in value.get("context_source_refs", [])
                if isinstance(item, dict)
            ),
            provider=_optional_text(value.get("provider")),
            model=_optional_text(value.get("model")),
            reasoning_policy=dict(value.get("reasoning_policy") or {}),
            created_at_ms=int(value.get("created_at_ms") or 0),
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
        }


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = [
    "CompletionDecision",
    "CompletionOutcome",
    "EvidenceRef",
    "RunContextManifest",
]
