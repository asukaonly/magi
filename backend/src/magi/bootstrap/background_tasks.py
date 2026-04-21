"""Bootstrap wiring for the background-task runtime.

This helper composes the persistence store, manager, dispatcher, launch
service, and completion-handshake listener into a single bundle that
:mod:`magi.agent.lifecycle` wires into ``AgentRuntimeModule``. Keeping
the plumbing here means the lifecycle module stays a thin assembly
site and the handshake callback has a single, well-named home.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

import structlog

from ..agent.background import (
    BackgroundDispatcher,
    BackgroundLaunchService,
    BackgroundTaskManager,
    BackgroundTaskRetentionGC,
    BackgroundTaskStore,
    build_background_run_fn,
)
from ..agent.execution.function_calling import FunctionCallingOrchestrator
from ..agent.runtime.types import TaskAgentType
from ..tools import tool_registry

if TYPE_CHECKING:
    from ..agent.background import BackgroundTask
    from ..agent.runtime import TaskAgentManager
    from ..agent.task_agents.chat_task_agent import ChatTaskAgent

logger = structlog.get_logger(__name__)


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
    retention_gc: BackgroundTaskRetentionGC


def build_background_task_wiring(
    *,
    store_db_path: str,
    llm_adapter: Any,
    llm_pool: Any,
    skill_runner: Any,
    runtime_trace_store: Any,
    max_concurrent: int = 2,
    history_retention_days: float = 0.0,
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
        llm_pool=llm_pool,
        skill_runner=skill_runner,
        runtime_trace_store=runtime_trace_store,
        scenario_llm_pool=llm_pool,
    )
    run_fn = build_background_run_fn(
        function_calling_orchestrator=orchestrator,
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
    retention_gc = BackgroundTaskRetentionGC(
        store=store,
        retention_days=history_retention_days,
    )
    return BackgroundTaskWiring(
        store=store,
        manager=manager,
        dispatcher=dispatcher,
        launch_service=launch_service,
        retention_gc=retention_gc,
    )


def build_completion_handshake_listener(
    *,
    get_task_agent_manager: Callable[[], "TaskAgentManager | None"],
    chat_agent_id: str = "default",
) -> Callable[["BackgroundTask"], Any]:
    """Return a listener that routes terminal tasks back to chat.

    The listener resolves the chat task agent via the ``TaskAgentManager``
    and invokes :meth:`ChatPostProcessService.deliver_background_task_completion`
    to post a system message into the task's originating session. Any
    exception is swallowed (but logged) so one bad task cannot break
    the manager's dispatch loop.
    """

    async def _handshake(task: "BackgroundTask") -> None:
        manager = get_task_agent_manager()
        if manager is None:
            logger.warning(
                "background task completion skipped - no task agent manager",
                bg_task_id=task.task_id,
            )
            return
        try:
            chat_agent = await manager.ensure_agent(TaskAgentType.CHAT, chat_agent_id)
        except Exception:  # noqa: BLE001 - defensive
            logger.exception(
                "background task completion could not resolve chat agent",
                bg_task_id=task.task_id,
            )
            return
        postprocess = getattr(chat_agent, "postprocess_service", None)
        if postprocess is None:
            logger.warning(
                "resolved chat agent exposes no postprocess_service",
                bg_task_id=task.task_id,
            )
            return
        try:
            await postprocess.deliver_background_task_completion(task)
        except Exception:  # noqa: BLE001 - listener isolation
            logger.exception(
                "background task completion handshake failed",
                bg_task_id=task.task_id,
            )

    return _handshake


__all__ = [
    "BackgroundTaskWiring",
    "build_background_task_wiring",
    "build_completion_handshake_listener",
]
