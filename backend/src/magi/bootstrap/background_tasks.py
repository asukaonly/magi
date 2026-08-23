"""Bootstrap wiring for the background-task runtime.

This helper composes the persistence store, manager, dispatcher, launch
service, and retention schedule contributor into a single bundle that
:mod:`magi.agent.lifecycle` wires into ``AgentRuntimeModule``. Keeping the
plumbing here means the lifecycle module stays a thin assembly site.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from magi.config.models import LLMScenario

from ..agent.background import (
    BackgroundDispatcher,
    BackgroundLaunchService,
    BackgroundTaskManager,
    BackgroundTaskRetentionScheduleContrib,
    BackgroundTaskStore,
    build_background_run_fn,
)
from ..agent.execution.function_calling import FunctionCallingOrchestrator
from ..tools import tool_registry


@dataclass(slots=True)
class BackgroundTaskWiring:
    """Runtime-owned background-task components.

    The dispatcher and launch service are shared by every chat agent
    instance (they are stateless). The manager owns concurrency state
    and the persistence store.
    """

    store: BackgroundTaskStore
    manager: BackgroundTaskManager
    dispatcher: BackgroundDispatcher
    launch_service: BackgroundLaunchService
    retention_schedule: BackgroundTaskRetentionScheduleContrib


def build_background_task_wiring(
    *,
    store_db_path: str,
    llm_adapter: Any,
    llm_pool: Any,
    skill_runner: Any,
    runtime_trace_store: Any,
    chat_task_budget_store: Any,
    max_concurrent: int = 2,
    permission_gateway_provider: Callable[[], Any] | None = None,
) -> BackgroundTaskWiring:
    """Construct the background-task components in their dependency order.

    The returned orchestrator-backed ``run_fn`` is fresh for this
    runtime and is *not* bound to any chat agent's callbacks, giving
    background runs their own runtime-trace identity as the design
    doc requires.
    """
    store = BackgroundTaskStore(db_path=store_db_path)
    orchestrator = FunctionCallingOrchestrator(
        tool_registry=tool_registry,
        llm_adapter=llm_adapter,
        active_model_provider=lambda: llm_pool.resolve(LLMScenario.CORE),
        skill_runner=skill_runner,
        runtime_trace_store=runtime_trace_store,
        scenario_llm_pool=llm_pool,
        permission_gateway_provider=permission_gateway_provider,
    )
    run_fn = build_background_run_fn(
        function_calling_orchestrator=orchestrator,
        chat_task_budget_store=chat_task_budget_store,
        background_task_budget_store=store,
    )
    manager = BackgroundTaskManager(
        store=store,
        run_fn=run_fn,
        max_concurrent=max_concurrent,
    )
    dispatcher = BackgroundDispatcher(
        llm_adapter=llm_adapter,
        llm_pool=llm_pool,
    )
    launch_service = BackgroundLaunchService(manager=manager)
    retention_schedule = BackgroundTaskRetentionScheduleContrib(
        store=store,
    )
    return BackgroundTaskWiring(
        store=store,
        manager=manager,
        dispatcher=dispatcher,
        launch_service=launch_service,
        retention_schedule=retention_schedule,
    )


__all__ = [
    "BackgroundTaskWiring",
    "build_background_task_wiring",
]
