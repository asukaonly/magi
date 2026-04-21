"""Backend bootstrap entrypoints and orchestrator wiring."""

from __future__ import annotations

from dependency_injector import providers

from ..config import AppConfig, get_config
from ..core.container import get_container
from ..core.logger import get_logger
from ..llm.factory import is_llm_selection_pending
from .context import RuntimeBootstrapContext
from .lifecycle import ModuleLifecycleOrchestrator
from .builder import build_runtime_modules
from ..llm.lifecycle import RuntimeInitializationDeferred

logger = get_logger(__name__)


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
    if context.plugins.sensor_registry is not None:
        container.sensor_registry.override(providers.Object(context.plugins.sensor_registry))
        bound.append("sensor_registry")
    if context.runtime_trace.store is not None:
        container.runtime_trace_store.override(providers.Object(context.runtime_trace.store))
        bound.append("runtime_trace_store")

    if bound:
        logger.info("Infrastructure bindings exported during deferred init: %s", ", ".join(bound))


def _initialize_skills_bindings_for_configuration_mode(config: AppConfig) -> None:
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
        from ..skills.service_access import build_skills_runtime

        bindings = build_skills_runtime(llm_adapter=None)
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
    """Check whether agent runtime has been initialized."""
    return _resolve_from_container("runtime_orchestrator") is not None


async def initialize_agent_runtime() -> None:
    """Initialize agent runtime on application startup."""
    if _is_runtime_initialized():
        logger.warning("Agent runtime already initialized")
        return

    context = RuntimeBootstrapContext()
    orchestrator = ModuleLifecycleOrchestrator(build_runtime_modules(context))

    try:
        logger.info("Initializing Agent Runtime...")
        await orchestrator.startup()
    except RuntimeInitializationDeferred as exc:
        _export_available_infrastructure_bindings(context)
        _initialize_skills_bindings_for_configuration_mode(context.core.config or get_config())
        if exc.pending_selection:
            logger.info(
                "LLM runtime initialization deferred: required selections are incomplete "
                "(context_decider/core provider+model)."
            )
        else:
            logger.warning("=" * 60)
            logger.warning("LLM runtime configuration is incomplete: %s", exc.cause)
            logger.warning("Agent runtime will NOT be initialized.")
            logger.warning("Configure an enabled core provider and model selection to enable AI responses.")
            logger.warning("=" * 60)
        return
    except Exception as exc:
        logger.error("Failed to initialize agent runtime: %s", exc, exc_info=True)
        raise

    container = get_container()
    container.runtime_orchestrator.override(providers.Object(orchestrator))
    container.runtime_bootstrap_context.override(providers.Object(context))
    logger.info("Agent runtime initialized successfully")


async def shutdown_agent_runtime() -> None:
    """Shutdown agent runtime."""
    orchestrator = _resolve_from_container("runtime_orchestrator")
    try:
        if orchestrator is not None:
            await orchestrator.shutdown()
    except Exception as exc:
        logger.error("Failed to stop agent runtime: %s", exc, exc_info=True)
    finally:
        container = get_container()
        container.runtime_orchestrator.reset_override()
        container.runtime_bootstrap_context.reset_override()
        logger.info("Agent runtime stopped")
