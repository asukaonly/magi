"""Test helpers for invoking the unified agent entry point."""

from __future__ import annotations

from typing import Any

from agent.permission_helpers import AllowAllPermissionGateway

from magi.agent.execution.function_calling.run_input import AgentRunRequest
from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY


async def run_agent(orchestrator: Any, **kwargs: Any) -> Any:
    """Build the production request object and invoke the single run entry."""

    if (
        getattr(orchestrator, "permission_gateway", None) is None
        and getattr(orchestrator, "_permission_gateway_provider", None) is None
    ):
        orchestrator.permission_gateway = AllowAllPermissionGateway()
    intent = kwargs.pop("intent", None)
    if intent is not None:
        kwargs["execution_preset"] = intent
    system_prompt = str(kwargs.get("system_prompt") or "").strip()
    if SYSTEM_PROMPT_CACHE_BOUNDARY not in system_prompt:
        kwargs["system_prompt"] = f"{system_prompt}\n{SYSTEM_PROMPT_CACHE_BOUNDARY}"
    return await orchestrator.run(AgentRunRequest(**kwargs))


__all__ = ["run_agent"]
