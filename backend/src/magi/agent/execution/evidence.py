"""Evidence collection helpers for completion decisions."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .contracts import EvidenceRef


@dataclass(frozen=True, slots=True)
class ToolExecutionEvidence:
    """Normalized completion-facing view of one tool invocation."""

    tool_name: str
    success: bool
    effect_class: str
    replay_policy: str
    error_code: str | None = None
    result: Any = None
    tool_call_id: str | None = None
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    @property
    def uncertain(self) -> bool:
        return self.error_code == "TOOL_EFFECT_UNCERTAIN"

    def to_ref(self) -> EvidenceRef:
        payload = {
            "tool_name": self.tool_name,
            "success": self.success,
            "effect_class": self.effect_class,
            "replay_policy": self.replay_policy,
            "error_code": self.error_code,
            "result": self.result,
            "tool_call_id": self.tool_call_id,
        }
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return EvidenceRef(
            evidence_id=uuid4().hex,
            kind="tool_execution",
            source=self.tool_name,
            status="succeeded" if self.success else "failed",
            payload_digest=hashlib.sha256(encoded).hexdigest(),
            created_at_ms=self.created_at_ms,
            metadata={
                "effect_class": self.effect_class,
                "replay_policy": self.replay_policy,
                "error_code": self.error_code,
                "tool_call_id": self.tool_call_id,
            },
        )


def successful_validation_evidence(
    evidence: list[ToolExecutionEvidence],
    *,
    validation_tool_names: frozenset[str],
) -> list[ToolExecutionEvidence]:
    """Return successful validation calls whose result does not report failures."""

    return [
        item
        for item in evidence
        if item.tool_name in validation_tool_names
        and item.success
        and not _result_reports_validation_failure(item.result)
    ]


def failed_validation_evidence(
    evidence: list[ToolExecutionEvidence],
    *,
    validation_tool_names: frozenset[str],
) -> list[ToolExecutionEvidence]:
    """Return validation calls that failed or reported invalid outputs."""

    return [
        item
        for item in evidence
        if item.tool_name in validation_tool_names
        and (
            not item.success
            or _result_reports_validation_failure(item.result)
        )
    ]


def _result_reports_validation_failure(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    summary = value.get("summary")
    if isinstance(summary, dict):
        failed = summary.get("failed")
        if isinstance(failed, (int, float)) and failed > 0:
            return True
        if summary.get("success") is False:
            return True
    results = value.get("results")
    if isinstance(results, list):
        return any(
            isinstance(item, dict)
            and (
                item.get("success") is False
                or str(item.get("status") or "").lower() in {"failed", "error", "invalid"}
            )
            for item in results
        )
    return value.get("success") is False


__all__ = [
    "ToolExecutionEvidence",
    "failed_validation_evidence",
    "successful_validation_evidence",
]
