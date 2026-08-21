"""Runtime state contracts for worker agent execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..cancel import EventCancelToken

WORKER_AGENT_PROGRESS = "WORKER_AGENT_PROGRESS"
WORKER_AGENT_COMPLETED = "WORKER_AGENT_COMPLETED"
WORKER_AGENT_FAILED = "WORKER_AGENT_FAILED"
DEFAULT_WORKER_MAX_ITERATIONS = 20
MAX_WORKER_MAX_ITERATIONS = 50
DEFAULT_WORKER_AWAIT_TIMEOUT_SECONDS = 300
MAX_WORKER_AWAIT_TIMEOUT_SECONDS = 300
WORKER_TOOL_TIMEOUT_SECONDS = 310


@dataclass
class WorkerRunState:
    """Runtime state for one worker execution."""

    worker_id: str
    subagent_type: str
    description: str
    prompt: str
    orchestration_id: str | None
    subtask_id: str | None
    parent_task_agent_type: str
    parent_task_agent_id: str
    target_task_agent_type: str
    target_task_agent_id: str
    user_id: str
    session_id: str
    turn_id: str | None
    created_at: float
    run_id: str | None = None
    run_revision: int = 0
    user_message_generation: int | None = None
    status: str = "running"
    updated_at: float = 0.0
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    result_preview: str | None = None
    error: str | None = None
    failure_reason: str | None = None
    retry_count: int = 0
    task: asyncio.Task | None = None
    cancel_token: EventCancelToken | None = None
    selected_tools: list[str] = field(default_factory=list)
    parent_context_summary: str = ""
    started_at_ms: int = 0
    started_monotonic: float = 0.0
    startup_committed: bool = False


def optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
