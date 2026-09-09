"""Backend bootstrap entrypoints and orchestrator wiring."""

from __future__ import annotations

import asyncio

from dependency_injector import providers

from ..config import AppConfig, get_config
from ..core.container import get_container
from ..core.logger import get_logger
from .context import RuntimeBootstrapContext
from .lifecycle import ModuleLifecycleOrchestrator
from .builder import build_runtime_modules
from .runtime_startup_state import set_runtime_startup_state
from .runtime_worker_builder import describe_runtime_worker_phase_plan

logger = get_logger(__name__)
_runtime_lifecycle_lock = asyncio.Lock()
_runtime_generation = 0
_runtime_stopping = False


def _bind_runtime_bootstrap_state(
    orchestrator: ModuleLifecycleOrchestrator,
    context: RuntimeBootstrapContext,
) -> None:
    """Expose the current bootstrap context and orchestrator through DI."""
    container = get_container()
    container.runtime_orchestrator.override(providers.Object(orchestrator))
    container.runtime_bootstrap_context.override(providers.Object(context))


def _resolve_from_container(attr: str):
    """Try to resolve a service from the DI container, return None on failure."""
    try:
        container = get_container()
        instance = getattr(container, attr)()
        if instance is not None and type(instance).__name__ != "object":
            return instance
    except Exception:
        pass
    return None


def refresh_runtime_llm_config(config: AppConfig | None = None) -> None:
    """Refresh cached runtime LLM adapters after configuration changes."""
    scenario_llm_pool = _resolve_from_container("scenario_llm_pool")
    if scenario_llm_pool is None:
        return

    next_config = config or get_config()
    scenario_llm_pool.refresh(next_config)
    logger.info("Runtime LLM pool refreshed after configuration update")


def _is_runtime_initialized() -> bool:
    """Check whether the full agent runtime is available for message handling."""
    return _resolve_from_container("agent_runtime") is not None


async def initialize_agent_runtime() -> None:
    """Serialize startup with configuration retries and shutdown."""
    generation = _runtime_generation
    if _runtime_stopping:
        return
    async with _runtime_lifecycle_lock:
        if generation != _runtime_generation or _runtime_stopping:
            return
        await _initialize_agent_runtime()


def _runtime_owner() -> tuple[ModuleLifecycleOrchestrator, RuntimeBootstrapContext]:
    orchestrator = _resolve_from_container("runtime_orchestrator")
    context = _resolve_from_container("runtime_bootstrap_context")
    if orchestrator is None:
        context = RuntimeBootstrapContext()
        orchestrator = ModuleLifecycleOrchestrator(build_runtime_modules(context))
        _bind_runtime_bootstrap_state(orchestrator, context)
    if context is None:
        raise RuntimeError("Runtime lifecycle context is missing")
    return orchestrator, context


async def initialize_base_runtime() -> None:
    """Open the management substrate before optional runtime startup."""
    async with _runtime_lifecycle_lock:
        orchestrator, _context = _runtime_owner()
        set_runtime_startup_state("starting")
        try:
            await orchestrator.startup(targets={"runtime_base_exports"})
        except Exception as exc:
            set_runtime_startup_state("failed", reason="base_init_failed", detail=str(exc))
            raise


async def _initialize_agent_runtime() -> None:
    """Resume capabilities on the existing owner while holding its lock."""
    orchestrator, context = _runtime_owner()
    set_runtime_startup_state("starting")
    try:
        context.core.config = get_config()
        pool = context.llm.scenario_llm_pool
        if pool is not None:
            pool.refresh(context.core.config)
            if orchestrator.is_ready("runtime_llm") and not context.runtime_commands.full_clear_recovery_pending:
                from ..llm.factory import create_core_llm_adapter

                try:
                    context.llm.llm_adapter = create_core_llm_adapter(pool)
                except Exception:
                    # Withdraw readiness even if a dependent resource cannot stop.
                    context.llm.llm_adapter = None
                    await orchestrator.shutdown(targets={"runtime_llm"}, strict=True)
        logger.info("Runtime worker phase plan: %s", describe_runtime_worker_phase_plan())
        await orchestrator.startup()
    except Exception as exc:
        set_runtime_startup_state("failed", reason="runtime_init_failed", detail=str(exc))
        raise

    states = orchestrator.snapshot()
    failed = [name for name, state in states.items() if state["state"] == "failed"]
    llm_state = states["runtime_llm"]
    if failed:
        set_runtime_startup_state("failed", reason="capability_init_failed", detail=", ".join(failed))
    elif llm_state["state"] == "blocked":
        reason = llm_state["reason"] or "llm_selection_pending"
        set_runtime_startup_state("deferred", reason=reason.removeprefix("runtime_"))
    elif _is_runtime_initialized():
        set_runtime_startup_state("ready")
    else:
        set_runtime_startup_state("deferred", reason="capabilities_pending")

    scheduler = context.scheduler.scheduler_service
    if scheduler is not None and not context.runtime_commands.full_clear_recovery_pending:
        await scheduler.refresh_availability()

    from .maintenance_worker import is_restore_worker
    if _is_runtime_initialized() and not is_restore_worker():
        from ..memory.portability.service import get_memory_portability_service
        try:
            await get_memory_portability_service().resume_restore_indexing()
        except Exception:
            logger.warning("Restore index rebuild remains pending", exc_info=True)


async def shutdown_agent_runtime(*, strict: bool = False) -> None:
    """Serialize shutdown with pending runtime initialization."""
    global _runtime_generation, _runtime_stopping
    _runtime_generation += 1
    _runtime_stopping = True
    try:
        async with _runtime_lifecycle_lock:
            await _shutdown_agent_runtime(strict=strict)
    finally:
        _runtime_stopping = False


async def _shutdown_agent_runtime(*, strict: bool = False) -> None:
    """Shutdown agent runtime.

    Args:
        strict: Re-raise shutdown failures while retaining lifecycle ownership.
            Storage maintenance uses this mode because replacing a database while
            any runtime module may still hold an open connection is unsafe.
    """
    orchestrator = _resolve_from_container("runtime_orchestrator")
    set_runtime_startup_state("stopping")
    shutdown_error: Exception | None = None
    try:
        if orchestrator is not None:
            await orchestrator.shutdown(strict=strict)
    except Exception as exc:
        shutdown_error = exc
        set_runtime_startup_state("failed", reason="runtime_shutdown_failed", detail=str(exc))
        logger.error("Failed to stop agent runtime: %s", exc, exc_info=True)
    finally:
        if shutdown_error is None or not strict:
            container = get_container()
            container.runtime_orchestrator.reset_override()
            container.runtime_bootstrap_context.reset_override()
            set_runtime_startup_state("offline")
            logger.info("Agent runtime stopped")
        else:
            logger.error("Agent runtime ownership retained for a strict shutdown retry")
    if strict and shutdown_error is not None:
        raise RuntimeError("Agent runtime could not be stopped safely") from shutdown_error
