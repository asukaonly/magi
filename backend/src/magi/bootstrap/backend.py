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


def get_master_agent():
    """Backward-compatible API: runtime mode has no MasterAgent instance."""
    return None


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
    return _resolve_from_container("agent_runtime") is not None


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


async def initialize_chat_agent() -> None:
    """Backward-compatible runtime initialization entrypoint."""
    await initialize_agent_runtime()


async def shutdown_chat_agent() -> None:
    """Backward-compatible runtime shutdown entrypoint."""
    await shutdown_agent_runtime()
