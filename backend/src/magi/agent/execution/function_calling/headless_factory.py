"""Composition-root factories for headless function-calling runs.

These thin factories let lower layers (e.g. ``magi.skills.subagent``) drive a
headless function-calling run without importing the agent execution engine
directly. The composition root injects them downward; the agent layer owns the
concrete ``FunctionCallingOrchestrator`` / ``EngineRunInput`` construction here.
"""

from __future__ import annotations

from typing import Any

from .orchestrator import FunctionCallingOrchestrator
from .run_input import EngineRunInput


def build_function_calling_orchestrator(
    *,
    llm_adapter: Any,
    tool_registry: Any,
    skill_runner: Any,
    tool_result_callback: Any,
    permission_gateway_provider: Any = None,
    active_model_provider: Any = None,
    scenario_llm_pool: Any = None,
) -> FunctionCallingOrchestrator:
    """Construct a :class:`FunctionCallingOrchestrator` for a headless run."""
    return FunctionCallingOrchestrator(
        llm_adapter=llm_adapter,
        tool_registry=tool_registry,
        skill_runner=skill_runner,
        tool_result_callback=tool_result_callback,
        permission_gateway_provider=permission_gateway_provider,
        active_model_provider=active_model_provider,
        scenario_llm_pool=scenario_llm_pool,
    )


def build_headless_engine_run_input(**kwargs: Any) -> EngineRunInput:
    """Build an :class:`EngineRunInput` for a headless (subagent) run."""
    return EngineRunInput.headless(**kwargs)
