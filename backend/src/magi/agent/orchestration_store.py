"""Persistent orchestration state store."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.logger import get_logger
from ..utils.runtime import get_runtime_paths
from .orchestration_models import TaskOrchestrationState, WorkerResult

logger = get_logger(__name__)


class OrchestrationStore:
    """Persist orchestration states and full worker results for task-agent recovery."""

    def __init__(self, file_path: Optional[Path] = None) -> None:
        runtime_paths = get_runtime_paths()
        self._file_path = file_path or runtime_paths.task_orchestrations_path
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
        worker_result: WorkerResult,
    ) -> None:
        async with self._lock:
            payload = self._load_payload()
            worker_results = payload.setdefault("worker_results", {})
            worker_results[worker_id] = {
                "worker_id": worker_id,
                "orchestration_id": orchestration_id,
                "subtask_id": subtask_id,
                "worker_result": worker_result.to_dict(),
                "updated_at": time.time(),
            }
            self._write_payload(payload)

    async def clear_all(self) -> dict[str, int]:
        """Remove every persisted orchestration and worker result atomically."""
        async with self._lock:
            payload = self._load_payload()
            orchestration_count = len(payload.get("orchestrations", {}))
            worker_result_count = len(payload.get("worker_results", {}))
            self._write_payload_or_raise(
                {"orchestrations": {}, "worker_results": {}}
            )
        return {
            "orchestrations": orchestration_count,
            "worker_results": worker_result_count,
        }

    async def get_worker_result(self, worker_id: str) -> Optional[WorkerResult]:
        async with self._lock:
            payload = self._load_payload()
        raw = payload.get("worker_results", {}).get(worker_id)
        if not isinstance(raw, dict):
            return None
        worker_result = raw.get("worker_result")
        return WorkerResult.from_dict(worker_result) if isinstance(worker_result, dict) else None

    def get_worker_result_sync(self, worker_id: str) -> Optional[WorkerResult]:
        payload = self._load_payload()
        raw = payload.get("worker_results", {}).get(worker_id)
        if not isinstance(raw, dict):
            return None
        worker_result = raw.get("worker_result")
        return WorkerResult.from_dict(worker_result) if isinstance(worker_result, dict) else None

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
            self._write_payload_or_raise(payload)
        except Exception as exc:
            logger.warning("Failed to write orchestration store | path=%s error=%s", self._file_path, exc)

    def _write_payload_or_raise(self, payload: Dict[str, Any]) -> None:
        from ..utils.file_io import atomic_write_text

        atomic_write_text(
            self._file_path,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )


_orchestration_store: Optional[OrchestrationStore] = None


def get_orchestration_store() -> OrchestrationStore:
    """Return the process-wide orchestration store."""
    global _orchestration_store
    if _orchestration_store is None:
        _orchestration_store = OrchestrationStore()
    return _orchestration_store


__all__ = ["OrchestrationStore", "get_orchestration_store"]
