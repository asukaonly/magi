"""Persistent orchestration state for parent task agents and worker results."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.logger import get_logger
from ..utils.runtime import get_runtime_paths

logger = get_logger(__name__)


RETRIABLE_WORKER_FAILURES = {
    "EMPTY_FINAL_RESPONSE",
    "LLM_RATE_LIMIT",
    "WORKER_TIMEOUT",
}


@dataclass
class WorkerResult:
    """Structured worker result consumed by parent task agents."""

    summary: str
    findings: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    subtasks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "WorkerResult":
        return cls(
            summary=str(payload.get("summary", "")).strip(),
            findings=_as_dict_list(payload.get("findings")),
            evidence=_as_dict_list(payload.get("evidence")),
            gaps=_as_string_list(payload.get("gaps")),
            next_steps=_as_string_list(payload.get("next_steps")),
            subtasks=_as_dict_list(payload.get("subtasks")),
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
    attempt_count: int = 0
    worker_result: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

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
            attempt_count=_safe_int(payload.get("attempt_count"), default=0),
            worker_result=payload.get("worker_result") if isinstance(payload.get("worker_result"), dict) else None,
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
    status: str = "running"
    retry_budget: int = 1
    allow_parallel: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None
    subtasks: List[SubtaskDefinition] = field(default_factory=list)
    final_response: Optional[str] = None

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
            planner=str(payload.get("planner", "task_agent")).strip() or "task_agent",
            status=str(payload.get("status", "running")).strip() or "running",
            retry_budget=_safe_int(payload.get("retry_budget"), default=1),
            allow_parallel=bool(payload.get("allow_parallel", True)),
            created_at=_safe_float(payload.get("created_at"), default=time.time()),
            updated_at=_safe_float(payload.get("updated_at"), default=time.time()),
            correlation_id=_optional_string(payload.get("correlation_id")),
            subtasks=subtasks,
            final_response=_optional_string(payload.get("final_response")),
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


class OrchestrationStore:
    """Persist orchestration states and full worker results for task-agent recovery."""

    def __init__(self, file_path: Optional[Path] = None) -> None:
        runtime_paths = get_runtime_paths()
        self._file_path = file_path or runtime_paths.data_dir / "task_orchestrations.json"
        self._lock = asyncio.Lock()

    async def save_orchestration(self, state: TaskOrchestrationState) -> None:
        async with self._lock:
            payload = self._load_payload()
            payload.setdefault("orchestrations", {})[state.orchestration_id] = state.to_dict()
            self._write_payload(payload)

    async def get_orchestration(self, orchestration_id: str) -> Optional[TaskOrchestrationState]:
        async with self._lock:
            payload = self._load_payload()
        raw = payload.get("orchestrations", {}).get(orchestration_id)
        if not isinstance(raw, dict):
            return None
        return TaskOrchestrationState.from_dict(raw)

    async def list_orchestrations(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        statuses: Optional[List[str]] = None,
    ) -> List[TaskOrchestrationState]:
        async with self._lock:
            payload = self._load_payload()
        items = []
        for value in payload.get("orchestrations", {}).values():
            if not isinstance(value, dict):
                continue
            state = TaskOrchestrationState.from_dict(value)
            if user_id and state.user_id != user_id:
                continue
            if session_id and state.session_id != session_id:
                continue
            if statuses and state.status not in statuses:
                continue
            items.append(state)
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    async def save_worker_result(
        self,
        worker_id: str,
        orchestration_id: Optional[str],
        subtask_id: Optional[str],
        worker_result: Dict[str, Any],
    ) -> None:
        async with self._lock:
            payload = self._load_payload()
            worker_results = payload.setdefault("worker_results", {})
            worker_results[worker_id] = {
                "worker_id": worker_id,
                "orchestration_id": orchestration_id,
                "subtask_id": subtask_id,
                "worker_result": worker_result,
                "updated_at": time.time(),
            }
            self._write_payload(payload)

    async def get_worker_result(self, worker_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            payload = self._load_payload()
        raw = payload.get("worker_results", {}).get(worker_id)
        if not isinstance(raw, dict):
            return None
        worker_result = raw.get("worker_result")
        return worker_result if isinstance(worker_result, dict) else None

    def get_worker_result_sync(self, worker_id: str) -> Optional[Dict[str, Any]]:
        payload = self._load_payload()
        raw = payload.get("worker_results", {}).get(worker_id)
        if not isinstance(raw, dict):
            return None
        worker_result = raw.get("worker_result")
        return worker_result if isinstance(worker_result, dict) else None

    def _load_payload(self) -> Dict[str, Any]:
        if not self._file_path.exists():
            return {"orchestrations": {}, "worker_results": {}}
        try:
            raw = self._file_path.read_text(encoding="utf-8")
            payload = json.loads(raw) if raw.strip() else {}
            if not isinstance(payload, dict):
                return {"orchestrations": {}, "worker_results": {}}
            payload.setdefault("orchestrations", {})
            payload.setdefault("worker_results", {})
            return payload
        except Exception as exc:
            logger.warning("Failed to load orchestration store | path=%s error=%s", self._file_path, exc)
            return {"orchestrations": {}, "worker_results": {}}

    def _write_payload(self, payload: Dict[str, Any]) -> None:
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to write orchestration store | path=%s error=%s", self._file_path, exc)


_orchestration_store: Optional[OrchestrationStore] = None


def get_orchestration_store() -> OrchestrationStore:
    """Return the process-wide orchestration store."""
    global _orchestration_store
    if _orchestration_store is None:
        _orchestration_store = OrchestrationStore()
    return _orchestration_store


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


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


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
