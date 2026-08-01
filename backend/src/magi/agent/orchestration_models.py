"""Task orchestration data models and serialization helpers."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


RETRIABLE_WORKER_FAILURES = {
    "EMPTY_FINAL_RESPONSE",
    "LLM_RATE_LIMIT",
    "WORKER_TIMEOUT",
}


@dataclass
class WorkerFinding:
    """One validated finding produced by a worker."""

    title: str
    detail: str
    path: Optional[str] = None
    why_it_matters: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "title": self.title,
            "detail": self.detail,
        }
        if self.path:
            payload["path"] = self.path
        if self.why_it_matters:
            payload["why_it_matters"] = self.why_it_matters
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> Optional["WorkerFinding"]:
        title = str(payload.get("title", "")).strip()
        detail = str(payload.get("detail", "")).strip()
        if not title or not detail:
            return None
        return cls(
            title=title,
            detail=detail,
            path=_optional_string(payload.get("path")),
            why_it_matters=_optional_string(payload.get("why_it_matters")),
        )


@dataclass
class WorkerEvidence:
    """One evidence record produced by a worker."""

    path: str
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "detail": self.detail}

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> Optional["WorkerEvidence"]:
        path = str(payload.get("path", "")).strip()
        detail = str(payload.get("detail", "")).strip()
        if not path or not detail:
            return None
        return cls(path=path, detail=detail)


@dataclass
class WorkerResult:
    """Structured worker result consumed by parent task agents."""

    summary: str
    result_status: str = "success"
    findings: List[WorkerFinding] = field(default_factory=list)
    evidence: List[WorkerEvidence] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    subtasks: List["PlannedSubtask"] = field(default_factory=list)
    failure_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "result_status": self.result_status,
            "findings": [item.to_dict() for item in self.findings],
            "evidence": [item.to_dict() for item in self.evidence],
            "gaps": list(self.gaps),
            "next_steps": list(self.next_steps),
            "subtasks": [item.to_dict() for item in self.subtasks],
            "failure_reason": self.failure_reason,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "WorkerResult":
        return cls(
            result_status=str(payload.get("result_status", "success")).strip() or "success",
            summary=str(payload.get("summary", "")).strip(),
            findings=_as_findings(payload.get("findings")),
            evidence=_as_evidence(payload.get("evidence")),
            gaps=_as_string_list(payload.get("gaps")),
            next_steps=_as_string_list(payload.get("next_steps")),
            subtasks=_as_planned_subtasks(payload.get("subtasks")),
            failure_reason=_optional_string(payload.get("failure_reason")),
        )


@dataclass
class PlannedSubtask:
    """Execution-ready leaf worker definition before persistence."""

    description: str
    subagent_type: str
    prompt: str
    parallel_group: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> Optional["PlannedSubtask"]:
        description = str(payload.get("description", "")).strip()
        prompt = str(payload.get("prompt", "")).strip()
        if not description or not prompt:
            return None
        return cls(
            description=description,
            subagent_type=str(payload.get("subagent_type", "CodeExplore")).strip() or "CodeExplore",
            prompt=prompt,
            parallel_group=str(payload.get("parallel_group", "default")).strip() or "default",
        )


@dataclass
class SubtaskPlan:
    """Normalized subtask plan returned by planning services."""

    summary: str = ""
    subtasks: List[PlannedSubtask] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "subtasks": [item.to_dict() for item in self.subtasks],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SubtaskPlan":
        raw_subtasks = payload.get("subtasks")
        subtasks: List[PlannedSubtask] = []
        if isinstance(raw_subtasks, list):
            for item in raw_subtasks:
                if not isinstance(item, dict):
                    continue
                normalized = PlannedSubtask.from_dict(item)
                if normalized is not None:
                    subtasks.append(normalized)
        return cls(
            summary=str(payload.get("summary", "")).strip(),
            subtasks=subtasks,
        )


@dataclass
class SubtaskDefinition:
    """One leaf worker task owned by a parent task agent orchestration."""

    subtask_id: str
    description: str
    subagent_type: str
    prompt: str
    parallel_group: str = "default"
    status: str = "pending"
    worker_id: Optional[str] = None
    failure_reason: Optional[str] = None
    failure_details: Optional[Dict[str, Any]] = None
    attempt_count: int = 0
    worker_result: Optional[WorkerResult] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["worker_result"] = self.worker_result.to_dict() if self.worker_result is not None else None
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SubtaskDefinition":
        return cls(
            subtask_id=str(payload.get("subtask_id", "")).strip(),
            description=str(payload.get("description", "")).strip(),
            subagent_type=str(payload.get("subagent_type", "")).strip(),
            prompt=str(payload.get("prompt", "")).strip(),
            parallel_group=str(payload.get("parallel_group", "default")).strip() or "default",
            status=str(payload.get("status", "pending")).strip() or "pending",
            worker_id=_optional_string(payload.get("worker_id")),
            failure_reason=_optional_string(payload.get("failure_reason")),
            failure_details=(
                dict(payload.get("failure_details"))
                if isinstance(payload.get("failure_details"), dict)
                else None
            ),
            attempt_count=_safe_int(payload.get("attempt_count"), default=0),
            worker_result=(
                WorkerResult.from_dict(payload.get("worker_result"))
                if isinstance(payload.get("worker_result"), dict)
                else None
            ),
            created_at=_safe_float(payload.get("created_at"), default=time.time()),
            updated_at=_safe_float(payload.get("updated_at"), default=time.time()),
        )


@dataclass
class TaskOrchestrationState:
    """Persistent state for one parent task orchestration."""

    orchestration_id: str
    user_id: str
    session_id: str
    root_user_message: str
    planner: str
    turn_id: Optional[str] = None
    user_message_generation: Optional[int] = None
    workspace_root: Optional[str] = None
    status: str = "running"
    retry_budget: int = 1
    allow_parallel: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    subtasks: List[SubtaskDefinition] = field(default_factory=list)
    final_response: Optional[str] = None
    aggregated_markdown: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["subtasks"] = [item.to_dict() for item in self.subtasks]
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TaskOrchestrationState":
        subtasks_payload = payload.get("subtasks")
        subtasks = []
        if isinstance(subtasks_payload, list):
            subtasks = [
                SubtaskDefinition.from_dict(item)
                for item in subtasks_payload
                if isinstance(item, dict)
            ]
        return cls(
            orchestration_id=str(payload.get("orchestration_id", "")).strip(),
            user_id=str(payload.get("user_id", "")).strip(),
            session_id=str(payload.get("session_id", "")).strip(),
            root_user_message=str(payload.get("root_user_message", "")).strip(),
            turn_id=_optional_string(payload.get("turn_id")),
            user_message_generation=_optional_non_negative_int(
                payload.get("user_message_generation")
            ),
            planner=str(payload.get("planner", "task_agent")).strip() or "task_agent",
            workspace_root=_optional_string(payload.get("workspace_root")),
            status=str(payload.get("status", "running")).strip() or "running",
            retry_budget=_safe_int(payload.get("retry_budget"), default=1),
            allow_parallel=bool(payload.get("allow_parallel", True)),
            created_at=_safe_float(payload.get("created_at"), default=time.time()),
            updated_at=_safe_float(payload.get("updated_at"), default=time.time()),
            correlation_id=_optional_string(payload.get("correlation_id")),
            metadata=dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {},
            subtasks=subtasks,
            final_response=_optional_string(payload.get("final_response")),
            aggregated_markdown=_optional_string(payload.get("aggregated_markdown")),
        )

    @property
    def pending_worker_ids(self) -> List[str]:
        return [item.worker_id for item in self.subtasks if item.status == "running" and item.worker_id]

    @property
    def completed_worker_ids(self) -> List[str]:
        return [item.worker_id for item in self.subtasks if item.status == "completed" and item.worker_id]

    @property
    def failed_worker_ids(self) -> List[str]:
        return [item.worker_id for item in self.subtasks if item.status == "failed" and item.worker_id]

    def get_subtask(self, subtask_id: str) -> Optional[SubtaskDefinition]:
        for item in self.subtasks:
            if item.subtask_id == subtask_id:
                return item
        return None


@dataclass
class OrchestrationExecutionResult:
    """Structured orchestration execution output consumed by handlers."""

    response: str = ""
    skip_emit: bool = False
    root_user_message: str = ""
    correlation_id: Optional[str] = None
    orchestration_id: Optional[str] = None
    message_started_at: Optional[float] = None
    turn_id: Optional[str] = None
    streamed: bool = False
    retracted: bool = False


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_findings(value: Any) -> List[WorkerFinding]:
    if not isinstance(value, list):
        return []
    findings: List[WorkerFinding] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        finding = WorkerFinding.from_dict(item)
        if finding is not None:
            findings.append(finding)
    return findings


def _as_evidence(value: Any) -> List[WorkerEvidence]:
    if not isinstance(value, list):
        return []
    evidence: List[WorkerEvidence] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        record = WorkerEvidence.from_dict(item)
        if record is not None:
            evidence.append(record)
    return evidence


def _as_planned_subtasks(value: Any) -> List[PlannedSubtask]:
    if not isinstance(value, list):
        return []
    subtasks: List[PlannedSubtask] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        subtask = PlannedSubtask.from_dict(item)
        if subtask is not None:
            subtasks.append(subtask)
    return subtasks


def _as_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_non_negative_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "OrchestrationExecutionResult",
    "PlannedSubtask",
    "RETRIABLE_WORKER_FAILURES",
    "SubtaskDefinition",
    "SubtaskPlan",
    "TaskOrchestrationState",
    "WorkerEvidence",
    "WorkerFinding",
    "WorkerResult",
]
