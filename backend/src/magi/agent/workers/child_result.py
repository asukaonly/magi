"""Typed evidence returned from a bounded child agent run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_CHILD_RESULT_RECORDS = 500


@dataclass(frozen=True, slots=True)
class ChildFinding:
    title: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "detail": self.detail}

    @classmethod
    def from_dict(cls, value: Any) -> "ChildFinding | None":
        if not isinstance(value, dict):
            return None
        title = str(value.get("title") or "").strip()
        detail = str(value.get("detail") or "").strip()
        return cls(title=title, detail=detail) if title and detail else None


@dataclass(frozen=True, slots=True)
class ChildEvidence:
    path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "detail": self.detail}

    @classmethod
    def from_dict(cls, value: Any) -> "ChildEvidence | None":
        if not isinstance(value, dict):
            return None
        path = str(value.get("path") or "").strip()
        detail = str(value.get("detail") or "").strip()
        return cls(path=path, detail=detail) if path and detail else None


@dataclass(frozen=True, slots=True)
class ChildArtifact:
    path: str
    operation: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "operation": self.operation}

    @classmethod
    def from_dict(cls, value: Any) -> "ChildArtifact | None":
        if not isinstance(value, dict):
            return None
        path = str(value.get("path") or "").strip()
        operation = str(value.get("operation") or "").strip()
        if not path or operation not in {"created", "modified", "deleted"}:
            return None
        return cls(path=path, operation=operation)


@dataclass(frozen=True, slots=True)
class ChildVerification:
    command: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "command": self.command,
            "status": self.status,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ChildVerification | None":
        if not isinstance(value, dict):
            return None
        command = str(value.get("command") or "").strip()
        status = str(value.get("status") or "").strip()
        detail = str(value.get("detail") or "").strip()
        if not command or status not in {"passed", "failed"} or not detail:
            return None
        return cls(command=command, status=status, detail=detail)


@dataclass(frozen=True, slots=True)
class ChildRunResult:
    """Validated result envelope returned to the parent loop as evidence."""

    summary: str
    result_status: str
    findings: tuple[ChildFinding, ...] = ()
    evidence: tuple[ChildEvidence, ...] = ()
    artifacts: tuple[ChildArtifact, ...] = ()
    verification: tuple[ChildVerification, ...] = ()
    records: tuple[dict[str, Any], ...] = ()
    gaps: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "result_status": self.result_status,
            "findings": [item.to_dict() for item in self.findings],
            "evidence": [item.to_dict() for item in self.evidence],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "verification": [item.to_dict() for item in self.verification],
            "records": [dict(item) for item in self.records],
            "gaps": list(self.gaps),
            "next_steps": list(self.next_steps),
            "failure_reason": self.failure_reason,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ChildRunResult":
        return cls(
            summary=str(value.get("summary") or "").strip(),
            result_status=str(value.get("result_status") or "").strip(),
            findings=tuple(
                item
                for raw in _list(value.get("findings"))
                if (item := ChildFinding.from_dict(raw)) is not None
            ),
            evidence=tuple(
                item
                for raw in _list(value.get("evidence"))
                if (item := ChildEvidence.from_dict(raw)) is not None
            ),
            artifacts=tuple(
                item
                for raw in _list(value.get("artifacts"))
                if (item := ChildArtifact.from_dict(raw)) is not None
            ),
            verification=tuple(
                item
                for raw in _list(value.get("verification"))
                if (item := ChildVerification.from_dict(raw)) is not None
            ),
            records=tuple(dict(item) for item in _list(value.get("records")) if isinstance(item, dict)),
            gaps=_strings(value.get("gaps")),
            next_steps=_strings(value.get("next_steps")),
            failure_reason=str(value.get("failure_reason") or "").strip() or None,
        )


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if (text := str(item or "").strip()))


__all__ = [
    "ChildArtifact",
    "ChildEvidence",
    "ChildFinding",
    "ChildRunResult",
    "ChildVerification",
    "MAX_CHILD_RESULT_RECORDS",
]
