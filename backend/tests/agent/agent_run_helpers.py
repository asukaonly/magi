"""Test helpers for invoking the unified agent entry point."""

from __future__ import annotations

from typing import Any

from magi.agent.execution.function_calling.run_input import AgentRunRequest


async def run_agent(orchestrator: Any, **kwargs: Any) -> Any:
    """Build the production request object and invoke the single run entry."""

    intent = kwargs.pop("intent", None)
    if intent is not None:
        kwargs["execution_preset"] = intent
    return await orchestrator.run(AgentRunRequest(**kwargs))


__all__ = ["run_agent"]
