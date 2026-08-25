"""Tests for deterministic chat turn admission policy."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from magi.agent.execution.reasoning import ReasoningPreference
from magi.agent.task_agents.common import IncomingFactKind
from magi.agent.task_agents.handlers.contracts import (
    ChatRuntimeContext,
    TraceDisplayMode,
)
from magi.chat.task_agent.turn_admission_service import ChatTurnAdmissionService


def _context(kind: IncomingFactKind) -> ChatRuntimeContext:
    return cast(
        ChatRuntimeContext,
        SimpleNamespace(
            incoming_fact_kind=kind,
            planner_fact=None,
            planner_fact_kind=IncomingFactKind.OTHER_FACT,
            latest_payload=SimpleNamespace(reasoning_preference=ReasoningPreference.AUTO.value),
        ),
    )


def test_user_message_exposes_collapsible_trace_entry() -> None:
    decision = ChatTurnAdmissionService().resolve(_context(IncomingFactKind.USER_MESSAGE))

    assert decision.run_kind == "unified_agent_run"
    assert decision.execution_mode is None
    assert decision.ux_plan.trace_display_mode is TraceDisplayMode.COLLAPSIBLE


def test_non_user_fact_keeps_trace_entry_hidden() -> None:
    decision = ChatTurnAdmissionService().resolve(_context(IncomingFactKind.OTHER_FACT))

    assert decision.run_kind == "non_user_fact"
    assert decision.ux_plan.trace_display_mode is TraceDisplayMode.NONE
