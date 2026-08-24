"""Typed contracts for timeline task-agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ....agent.runtime.contracts import FactRecord
from ....agent.runtime.task_agent import (
    TaskAgentAdmissionDecision,
    TaskAgentCapabilitySelection,
    TaskAgentExecutionRequest,
    TaskAgentRuntimeContext,
)


@dataclass(slots=True)
class TimelinePayload:
    """Normalized timeline payload extracted from incoming facts."""

    source_type: str
    source_item_id: Optional[str] = None
    content: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TimelineRuntimeContext(TaskAgentRuntimeContext):
    """Runtime context for timeline fact handling."""

    batch_facts: list[FactRecord] = field(default_factory=list)
    latest_payload: Optional[TimelinePayload] = None


@dataclass(slots=True)
class TimelineAdmissionDecision(TaskAgentAdmissionDecision):
    """Timeline fact-admission outcome."""

    run_kind: str = "timeline_ingest"
    execution_mode: str = "timeline_fact_only"


@dataclass(slots=True)
class TimelineCapabilitySelection(TaskAgentCapabilitySelection):
    """Timeline capability-selection result."""


@dataclass(slots=True)
class TimelineExecutionRequest(TaskAgentExecutionRequest):
    """Timeline execution payload."""

    payload: Optional[TimelinePayload] = None


@dataclass(slots=True)
class TimelineExecutionResult:
    """Timeline execution result payload."""

    handled: bool
    payload: Optional[TimelinePayload] = None
