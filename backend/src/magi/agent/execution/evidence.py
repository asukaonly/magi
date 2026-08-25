"""Evidence collection helpers for completion decisions."""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
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
    evidence_id: str = field(default_factory=lambda: uuid4().hex)

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
            "result": deepcopy(self.result),
            "tool_call_id": self.tool_call_id,
        }
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return EvidenceRef(
            evidence_id=self.evidence_id,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "tool_name": self.tool_name,
            "success": self.success,
            "effect_class": self.effect_class,
            "replay_policy": self.replay_policy,
            "error_code": self.error_code,
            "result": self.result,
            "tool_call_id": self.tool_call_id,
            "created_at_ms": self.created_at_ms,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ToolExecutionEvidence":
        return cls(
            evidence_id=str(value["evidence_id"]),
            tool_name=str(value["tool_name"]),
            success=bool(value["success"]),
            effect_class=str(value["effect_class"]),
            replay_policy=str(value["replay_policy"]),
            error_code=(str(value["error_code"]) if value.get("error_code") is not None else None),
            result=deepcopy(value.get("result")),
            tool_call_id=(
                str(value["tool_call_id"]) if value.get("tool_call_id") is not None else None
            ),
            created_at_ms=int(value["created_at_ms"]),
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
        and not _result_reports_validation_inconclusive(item.result)
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
        and (not item.success or _result_reports_validation_failure(item.result))
    ]


def inconclusive_validation_evidence(
    evidence: list[ToolExecutionEvidence],
    *,
    validation_tool_names: frozenset[str],
) -> list[ToolExecutionEvidence]:
    """Return validation calls that completed without checking every target."""

    return [
        item
        for item in evidence
        if item.tool_name in validation_tool_names
        and item.success
        and _result_reports_validation_inconclusive(item.result)
    ]


def _result_reports_validation_failure(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    summary = value.get("summary")
    if isinstance(summary, dict):
        failed = summary.get("fail")
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
                or str(item.get("status") or "").lower() in {"fail", "error", "invalid"}
            )
            for item in results
        )
    return value.get("success") is False


def _result_reports_validation_inconclusive(value: Any) -> bool:
    """Return whether structured validation completed without checking every target."""

    if not isinstance(value, dict):
        return False
    summary = value.get("summary")
    if isinstance(summary, dict):
        for key in ("skipped", "timeout"):
            count = summary.get(key)
            if isinstance(count, (int, float)) and count > 0:
                return True
    results = value.get("results")
    return isinstance(results, list) and any(
        isinstance(item, dict) and str(item.get("status") or "").lower() in {"skipped", "timeout"}
        for item in results
    )


__all__ = [
    "ToolExecutionEvidence",
    "failed_validation_evidence",
    "inconclusive_validation_evidence",
    "successful_validation_evidence",
]
