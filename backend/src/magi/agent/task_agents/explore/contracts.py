"""Typed contracts for the ExploreTaskAgent pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ....core.runtime.contracts import FactRecord
from ..common import ExecutionMode, IncomingFactKind, OrchestrationPlan


@dataclass(slots=True)
class ExploreRuntimeContext:
    """Runtime context for ExploreTaskAgent turns."""

    latest_fact: Optional[FactRecord]
    recent_facts: list[FactRecord]
    batch_facts: list[FactRecord]
    agent_id: str
    agent_type: str
    runtime_key: str
    user_id: str
    session_id: str
    history_key: str
    history: list[dict[str, Any]]
    latest_user_message: str
    incoming_fact_kind: IncomingFactKind
    upstream_task_agent_type: str
    upstream_task_agent_id: str
    latest_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExploreIntentDecision:
    """Typed intent result for ExploreTaskAgent."""

    intent: str
    execution_mode: ExecutionMode
    orchestration_plan: Optional[OrchestrationPlan] = None
    reasoning: str = ""


@dataclass(slots=True)
class ExploreParseOutcome:
    """Post-processing outcome for ExploreTaskAgent results."""

    emitted: bool
