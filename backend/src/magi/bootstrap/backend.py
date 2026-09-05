"""Backend bootstrap entrypoints and orchestrator wiring."""

from __future__ import annotations

from dependency_injector import providers

from ..config import AppConfig, get_config
from ..core.container import get_container
from ..core.logger import get_logger
from .context import RuntimeBootstrapContext
from .lifecycle import ModuleLifecycleOrchestrator
from .builder import build_runtime_modules
from ..llm.lifecycle import RuntimeInitializationDeferred
from .runtime_startup_state import set_runtime_startup_state
from .runtime_worker_builder import describe_runtime_worker_phase_plan

logger = get_logger(__name__)


def _bind_runtime_bootstrap_state(
    orchestrator: ModuleLifecycleOrchestrator,
    context: RuntimeBootstrapContext,
) -> None:
    """Expose the current bootstrap context and orchestrator through DI."""
    container = get_container()
    container.runtime_orchestrator.override(providers.Object(orchestrator))
    container.runtime_bootstrap_context.override(providers.Object(context))


def _export_available_infrastructure_bindings(context: RuntimeBootstrapContext) -> None:
    """Bind infrastructure services that were created before LLM init was deferred.

    When ``LLMRuntimeModule`` raises ``LifecycleInitDeferred``, modules that
    ran *before* it (chat_store, message_bus, runtime_command_queue, etc.)
    have already been initialised.  Export them to the DI container so that
    API endpoints can use basic infrastructure even without a full runtime.
    """
    container = get_container()
    bound: list[str] = []

    if context.chat.store is not None:
        container.chat_store.override(providers.Object(context.chat.store))
        from ..chat.message_notifications import chat_message_notifier

        container.chat_message_notifier.override(providers.Object(chat_message_notifier))
        bound.append("chat_store")
    if context.message_bus.message_bus is not None:
        container.message_bus.override(providers.Object(context.message_bus.message_bus))
        bound.append("message_bus")
    if context.runtime_commands.runtime_command_queue is not None:
        container.runtime_command_queue.override(
            providers.Object(context.runtime_commands.runtime_command_queue),
        )
        bound.append("runtime_command_queue")
    if context.plugins.plugin_manager is not None:
        container.plugin_manager.override(providers.Object(context.plugins.plugin_manager))
        bound.append("plugin_manager")
    if context.plugins.plugin_projection_service is not None:
        container.plugin_projection_service.override(
            providers.Object(context.plugins.plugin_projection_service)
        )
        bound.append("plugin_projection_service")
    if context.plugins.sensor_registry is not None:
        container.sensor_registry.override(providers.Object(context.plugins.sensor_registry))
        bound.append("sensor_registry")
    if context.runtime_trace.store is not None:
        container.runtime_trace_store.override(providers.Object(context.runtime_trace.store))
        bound.append("runtime_trace_store")
    if context.chat.store is not None and context.runtime_commands.runtime_command_queue is not None:
        from ..chat.ingress import dispatch_user_message

        container.user_message_dispatcher.override(providers.Object(dispatch_user_message))
        bound.append("user_message_dispatcher")

    if bound:
        logger.info("Infrastructure bindings exported during deferred init: %s", ", ".join(bound))


def _initialize_skills_bindings_for_configuration_mode(
    config: AppConfig, context: RuntimeBootstrapContext,
) -> None:
    """Initialize skills bindings even when full runtime startup is deferred.

    During onboarding/configuration, LLM selection may be incomplete, which defers
    full runtime startup. The settings UI still needs skill metadata, so expose
    lightweight skills services via DI container in that state.
    """
    container = get_container()

    if not config.features.enable_skills:
        container.skill_indexer.reset_override()
        container.skill_loader.reset_override()
        container.skill_runner.reset_override()
        return

    try:
        from ..agent.execution.function_calling.headless_factory import (
            build_function_calling_orchestrator,
            build_headless_agent_run_request,
        )
        from ..skills.service_access import build_skills_runtime
        from ..tools import tool_registry

        bindings = build_skills_runtime(
            llm_adapter=None,
            tool_registry=tool_registry,
            orchestrator_factory=build_function_calling_orchestrator,
            agent_run_request_factory=build_headless_agent_run_request,
            skill_indexer=context.skills.skill_indexer,
            skill_loader=context.skills.skill_loader,
        )
        container.skill_indexer.override(providers.Object(bindings.skill_indexer))
        container.skill_loader.override(providers.Object(bindings.skill_loader))
        container.skill_runner.override(providers.Object(bindings.skill_runner))
        logger.info("Skills bindings initialized for configuration mode")
    except Exception as exc:
        logger.warning("Failed to initialize skills bindings for configuration mode: %s", exc)


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
    """Initialize agent runtime on application startup."""
    if _is_runtime_initialized():
        set_runtime_startup_state("ready")
        logger.warning("Agent runtime already initialized")
        return

    existing_orchestrator = _resolve_from_container("runtime_orchestrator")
    if existing_orchestrator is not None:
        logger.info("Cleaning up previously deferred runtime before reinitializing")
        await shutdown_agent_runtime()

    context = RuntimeBootstrapContext()
    orchestrator = ModuleLifecycleOrchestrator(build_runtime_modules(context))
    set_runtime_startup_state("starting")

    try:
        logger.info("Initializing Agent Runtime...")
        logger.info("Runtime worker phase plan: %s", describe_runtime_worker_phase_plan())
        await orchestrator.startup()
    except RuntimeInitializationDeferred as exc:
        _bind_runtime_bootstrap_state(orchestrator, context)
        _export_available_infrastructure_bindings(context)
        _initialize_skills_bindings_for_configuration_mode(context.core.config or get_config(), context)
        deferred_reason = "llm_selection_pending" if exc.pending_selection else "llm_configuration_invalid"
        set_runtime_startup_state(
            "deferred",
            reason=deferred_reason,
            detail=str(exc.cause) if exc.cause else None,
        )
        if exc.pending_selection:
            logger.info(
                "LLM runtime initialization deferred: required selections are incomplete "
                "(core provider+model)."
            )
        else:
            logger.warning("=" * 60)
            logger.warning("LLM runtime configuration is incomplete: %s", exc.cause)
            logger.warning("Agent runtime will NOT be initialized.")
            logger.warning("Configure an enabled core provider and model selection to enable AI responses.")
            logger.warning("=" * 60)
        return
    except Exception as exc:
        set_runtime_startup_state("failed", reason="runtime_init_failed", detail=str(exc))
        logger.error("Failed to initialize agent runtime: %s", exc, exc_info=True)
        raise

    _bind_runtime_bootstrap_state(orchestrator, context)
    set_runtime_startup_state("ready")
    logger.info("Agent runtime initialized successfully")


async def shutdown_agent_runtime(*, strict: bool = False) -> None:
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
