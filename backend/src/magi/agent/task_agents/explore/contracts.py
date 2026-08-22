"""Typed contracts for the ExploreTaskAgent pipeline."""
from __future__ import annotations

from dataclasses import dataclass

from ..common import BaseIntentDecision, BaseRuntimeContext


@dataclass(slots=True, kw_only=True)
class ExploreRuntimeContext(BaseRuntimeContext):
    """Runtime context for ExploreTaskAgent turns."""

    upstream_task_agent_type: str
    upstream_task_agent_id: str
    root_turn_id: str | None = None


@dataclass(slots=True, kw_only=True)
class ExploreIntentDecision(BaseIntentDecision):
    """Typed intent result for ExploreTaskAgent."""


@dataclass(slots=True)
class ExploreParseOutcome:
    """Post-processing outcome for ExploreTaskAgent results."""

    emitted: bool
