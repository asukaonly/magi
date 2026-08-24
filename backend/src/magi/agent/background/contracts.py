"""Dataclasses and enums describing a background task and its event log.

These types are the serialization boundary between the runtime layer (phases
1+) and the persistence layer (phase 0). They intentionally carry no
behavior — the store owns IO, the manager owns lifecycle transitions.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any

from magi_plugin_sdk.run_trigger import RunRequest, RunTrigger
from uuid import uuid4


class BackgroundTaskStatus(str, Enum):
    """Lifecycle states for a background task.

    The valid transitions are:

    * ``pending`` → ``running`` (slot acquired) | ``cancelled``
    * ``running`` → ``cancelling`` | ``succeeded`` | ``failed``
      | ``suspended_waiting_user``
    * ``suspended_waiting_user`` → ``running`` (user answered the prompt)
      | ``cancelling``
    * ``cancelling`` → ``cancelled``
    * ``failed`` / ``cancelled`` → ``pending`` on retry (new ``attempt_index``)

    Succeeded tasks are terminal.
    """

    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUSPENDED_WAITING_USER = "suspended_waiting_user"

    @classmethod
    def terminal(cls) -> frozenset["BackgroundTaskStatus"]:
        return frozenset({cls.SUCCEEDED, cls.FAILED, cls.CANCELLED})

    @property
    def is_terminal(self) -> bool:
        return self in self.terminal()


class BackgroundTaskTriggerSource(str, Enum):
    """How a task was launched. Used for auditing and dispatcher metrics."""

    PLANNER = "planner"  # LLM planner returned run_in_background=true
    CLASSIFIER = "classifier"  # long-task classifier (LLM slow path)
    USER = "user"  # user message explicitly asked for background
    MANUAL = "manual"  # UI "move to background" action
    RULE = "rule"  # dispatcher rule fast-path match
    SCHEDULE = "schedule"  # scheduler-created agent task

    @classmethod
    def from_trigger(cls, trigger: "RunTrigger | None") -> "BackgroundTaskTriggerSource":
        """Derive the coarse launch-source enum from a unified ``RunTrigger``.

        ADR-0004 P3 makes ``RunTrigger`` the source of truth for run
        provenance; this folds its ``trigger_type`` down to the legacy
        auditing enum so a background task launched from a detaching chat run
        keeps its origin in metrics instead of being blanket-tagged. The rich
        provenance (e.g. the external channel) still lives on the ``trigger``
        itself — this is only the coarse bucket.

        A ``None`` trigger (a run predating trigger propagation) yields
        ``MANUAL`` — the historical detach default. Unknown / future trigger
        types degrade to ``RULE`` rather than raising.
        """
        if trigger is None:
            return cls.MANUAL
        return _TRIGGER_SOURCE_BY_TRIGGER_TYPE.get(trigger.trigger_type, cls.RULE)


# trigger_type → coarse BackgroundTaskTriggerSource. Defined at module level
# (resolved at call time by ``from_trigger``) so the mapping table is visible
# and testable on its own. Trigger types absent here fall through to ``RULE``.
_TRIGGER_SOURCE_BY_TRIGGER_TYPE: dict[str, BackgroundTaskTriggerSource] = {
    "user_message": BackgroundTaskTriggerSource.USER,
    "user_steer": BackgroundTaskTriggerSource.USER,
    "user_retract": BackgroundTaskTriggerSource.USER,
    "external_inbound": BackgroundTaskTriggerSource.USER,
    "scheduled": BackgroundTaskTriggerSource.SCHEDULE,
    "background_resume": BackgroundTaskTriggerSource.MANUAL,
    "sensor_event": BackgroundTaskTriggerSource.RULE,
    "agent_self": BackgroundTaskTriggerSource.RULE,
    "child_run_completed": BackgroundTaskTriggerSource.RULE,
    "batch": BackgroundTaskTriggerSource.RULE,
}


@dataclass(slots=True)
class BackgroundTaskSpec:
    """Immutable input used to (re-)launch a background task.

    A spec is created once at dispatch time and is preserved verbatim across
    retries; the mutable state lives on :class:`BackgroundTask`.
    """

    user_id: str
    session_id: str
    origin_turn_id: str
    title: str
    goal: str
    selected_tools: list[str] = field(default_factory=list)
    workspace_path: str | None = None
    trigger_source: BackgroundTaskTriggerSource = BackgroundTaskTriggerSource.RULE
    # ADR-0004 P3: unified RunTrigger provenance carried alongside the legacy
    # trigger_source enum (additive). PR-3 will fold trigger_source into this so
    # chat / scheduler / batch all describe their run the same way.
    trigger: RunTrigger | None = None
    priority: int = 0
    max_iterations: int = 50
    timeout_seconds: int | None = 1800
    task_budget_root_turn_id: str | None = None
    """Root chat turn whose durable execution budget this task continues.

    Detached and chat-dispatched tasks set this value. Standalone scheduled,
    batch, and manually-created tasks leave it unset and use ``task_id`` as
    their background-owned budget identity.
    """
    agent_run_checkpoint: dict[str, Any] | None = None
    """Complete unified-loop checkpoint used for foreground handoff."""
    pending_message_id: str | None = None
    """Id of the placeholder ``background_task_pending`` chat message.

    When set, ``persist_completion_message`` will mark the pending row
    replaced by the freshly written completion row, so the UI displays
    exactly one entry for the task across its lifecycle.
    Only set by the ``/api/commands/run-skill-as-background`` flow
    today; legacy detach paths leave it ``None``.
    """

    def as_run_request(self) -> RunRequest:
        """Project this background spec into a unified ``RunRequest`` (ADR-0004 P3).

        The seam every driver shares: a ``RunRequest`` describes *what to run
        and for whom* (trigger + input + session + bounds), independent of the
        background-specific *how* (retry / snapshot / pending-message wiring)
        that stays on the spec. Falls back to a ``background_resume`` trigger
        when the spec predates trigger propagation.
        """
        trigger = self.trigger or RunTrigger(
            trigger_type="background_resume",
            source_channel=None,
            requester=self.user_id,
            priority="background",
        )
        return RunRequest(
            trigger=trigger,
            input={"goal": self.goal},
            session_id=self.session_id,
            bounds={
                "max_iterations": self.max_iterations,
                "timeout_seconds": self.timeout_seconds,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "origin_turn_id": self.origin_turn_id,
            "title": self.title,
            "goal": self.goal,
            "selected_tools": list(self.selected_tools),
            "workspace_path": self.workspace_path,
            "trigger_source": self.trigger_source.value,
            "trigger": self.trigger.to_dict() if self.trigger else None,
            "priority": int(self.priority),
            "max_iterations": int(self.max_iterations),
            "timeout_seconds": (
                int(self.timeout_seconds) if self.timeout_seconds is not None else None
            ),
            "task_budget_root_turn_id": self.task_budget_root_turn_id,
            "agent_run_checkpoint": (
                deepcopy(self.agent_run_checkpoint)
                if self.agent_run_checkpoint is not None
                else None
            ),
            "pending_message_id": self.pending_message_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackgroundTaskSpec":
        return cls(
            user_id=str(data["user_id"]),
            session_id=str(data["session_id"]),
            origin_turn_id=str(data["origin_turn_id"]),
            title=str(data["title"]),
            goal=str(data["goal"]),
            selected_tools=list(data.get("selected_tools") or []),
            workspace_path=(
                str(data["workspace_path"]) if data.get("workspace_path") is not None else None
            ),
            trigger_source=BackgroundTaskTriggerSource(
                str(data.get("trigger_source") or BackgroundTaskTriggerSource.RULE.value)
            ),
            trigger=(
                RunTrigger.from_dict(data["trigger"]) if data.get("trigger") is not None else None
            ),
            priority=int(data.get("priority") or 0),
            max_iterations=int(data.get("max_iterations") or 20),
            timeout_seconds=(
                int(data["timeout_seconds"]) if data.get("timeout_seconds") is not None else None
            ),
            task_budget_root_turn_id=(
                str(data["task_budget_root_turn_id"])
                if data.get("task_budget_root_turn_id") is not None
                else None
            ),
            agent_run_checkpoint=(
                deepcopy(data["agent_run_checkpoint"])
                if data.get("agent_run_checkpoint") is not None
                else None
            ),
            pending_message_id=(
                str(data["pending_message_id"])
                if data.get("pending_message_id") is not None
                else None
            ),
        )


@dataclass(slots=True)
class BackgroundTask:
    """Mutable runtime state for one background task.

    ``task_id`` is stable across retries; each retry bumps ``attempt_index``
    and clears ``started_at`` / ``finished_at`` / ``error`` / ``summary`` /
    ``result_payload`` / ``orchestration_id`` before transitioning back to
    ``pending``.
    """

    task_id: str
    spec: BackgroundTaskSpec
    status: BackgroundTaskStatus = BackgroundTaskStatus.PENDING
    attempt_index: int = 0
    orchestration_id: str | None = None
    user_task_id: str | None = None
    summary: str | None = None
    result_payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    cancel_reason: str | None = None
    created_at: float = field(default_factory=time)
    started_at: float | None = None
    finished_at: float | None = None
    updated_at: float = field(default_factory=time)

    @classmethod
    def new(cls, spec: BackgroundTaskSpec) -> "BackgroundTask":
        """Build a fresh task in ``pending`` state."""
        now = time()
        return cls(
            task_id=f"bg_{uuid4().hex[:16]}",
            spec=spec,
            status=BackgroundTaskStatus.PENDING,
            attempt_index=0,
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "spec": self.spec.to_dict(),
            "status": self.status.value,
            "attempt_index": int(self.attempt_index),
            "orchestration_id": self.orchestration_id,
            "user_task_id": self.user_task_id,
            "summary": self.summary,
            "result_payload": dict(self.result_payload),
            "error": self.error,
            "cancel_reason": self.cancel_reason,
            "created_at": float(self.created_at),
            "started_at": (float(self.started_at) if self.started_at is not None else None),
            "finished_at": (float(self.finished_at) if self.finished_at is not None else None),
            "updated_at": float(self.updated_at),
        }


@dataclass(slots=True)
class BackgroundTaskEvent:
    """An append-only entry in the task's event log.

    Events are recorded for every state transition plus ad-hoc progress
    notes. The store guarantees insertion order but does not enforce any
    transition validity; the manager is the authority on legal transitions.
    """

    event_id: str
    task_id: str
    attempt_index: int
    event_type: str
    from_status: BackgroundTaskStatus | None
    to_status: BackgroundTaskStatus | None
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time)

    @classmethod
    def transition(
        cls,
        *,
        task_id: str,
        attempt_index: int,
        from_status: BackgroundTaskStatus | None,
        to_status: BackgroundTaskStatus,
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> "BackgroundTaskEvent":
        return cls(
            event_id=uuid4().hex,
            task_id=task_id,
            attempt_index=int(attempt_index),
            event_type="state_changed",
            from_status=from_status,
            to_status=to_status,
            message=message,
            payload=dict(payload or {}),
        )

    @classmethod
    def progress(
        cls,
        *,
        task_id: str,
        attempt_index: int,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> "BackgroundTaskEvent":
        return cls(
            event_id=uuid4().hex,
            task_id=task_id,
            attempt_index=int(attempt_index),
            event_type="progress",
            from_status=None,
            to_status=None,
            message=message,
            payload=dict(payload or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "attempt_index": int(self.attempt_index),
            "event_type": self.event_type,
            "from_status": self.from_status.value if self.from_status is not None else None,
            "to_status": self.to_status.value if self.to_status is not None else None,
            "message": self.message,
            "payload": dict(self.payload),
            "created_at": float(self.created_at),
        }
