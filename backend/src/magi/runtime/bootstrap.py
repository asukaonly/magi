"""Agent runtime bootstrap and lifecycle wiring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..config import AppConfig, get_config
from ..core.container import get_container
from ..core.logger import get_logger
from ..memory import UnifiedMemoryStore
from ..memory.integration import MemoryIntegrationModule
from ..context.scenario_prompts import ScenarioPromptsStore
from ..scheduler import SchedulerService
from .lifecycle import ModuleLifecycleOrchestrator
from ..llm.factory import is_llm_selection_pending as _is_llm_selection_pending_impl
from .runtime_modules import (
    RuntimeBootstrapState,
    RuntimeInitializationDeferred,
    build_runtime_modules,
)

logger = get_logger(__name__)

_runtime_orchestrator: ModuleLifecycleOrchestrator | None = None
_runtime_state: RuntimeBootstrapState | None = None


@dataclass
class RuntimeBindings:
    """External callbacks used to bridge runtime with upper layers."""

    get_current_personality: Optional[Callable[[], str]] = None
    set_message_bus: Optional[Callable[[Any], None]] = None
    init_skills_module: Optional[Callable[[Any], None]] = None


_bindings = RuntimeBindings()


def configure_runtime_bindings(bindings: RuntimeBindings | None = None) -> None:
    """Configure runtime bridge callbacks from outer app entrypoint."""
    global _bindings
    _bindings = bindings or RuntimeBindings()


def get_master_agent():
    """Backward-compatible API: runtime mode has no MasterAgent instance."""
    return None


def _resolve_from_container(attr: str) -> Any:
    """Try to resolve a service from the DI container, return None on failure."""
    try:
        container = get_container()
        instance = getattr(container, attr)()
        if instance is not None and type(instance).__name__ != "object":
            return instance
    except Exception:
        pass
    return None


def get_memory_integration() -> MemoryIntegrationModule:
    """Get memory integration module."""
    instance = _resolve_from_container("memory_integration")
    if instance is not None:
        return instance
    raise RuntimeError("MemoryIntegrationModule not initialized. Call initialize_agent_runtime() first.")


def get_unified_memory() -> UnifiedMemoryStore:
    """Get unified memory store."""
    return get_memory_integration().unified_memory


def get_agent_runtime():
    """Get agent runtime."""
    instance = _resolve_from_container("agent_runtime")
    if instance is not None:
        return instance
    raise RuntimeError("AgentRuntime not initialized. Call initialize_agent_runtime() first.")


def get_scheduler_service() -> SchedulerService:
    """Get the active scheduler service."""
    instance = _resolve_from_container("scheduler_service")
    if instance is not None:
        return instance
    raise RuntimeError("SchedulerService not initialized. Call initialize_agent_runtime() first.")


def refresh_runtime_llm_config(config: AppConfig | None = None) -> None:
    """Refresh cached runtime LLM adapters after configuration changes."""
    scenario_llm_pool = _resolve_from_container("scenario_llm_pool")
    if scenario_llm_pool is None:
        return

    next_config = config or get_config()
    scenario_llm_pool.refresh(next_config)
    logger.info("Runtime LLM pool refreshed after configuration update")


def _is_llm_selection_pending(config: AppConfig) -> bool:
    """Backward-compatible proxy for runtime LLM selection readiness checks."""
    return _is_llm_selection_pending_impl(config)


def _is_runtime_initialized() -> bool:
    """Check whether agent runtime has been initialized."""
    return _runtime_state is not None and _runtime_state.agent_runtime is not None


async def initialize_agent_runtime() -> None:
    """Initialize agent runtime on application startup."""
    global _runtime_orchestrator, _runtime_state

    if _is_runtime_initialized():
        logger.warning("Agent runtime already initialized")
        return

    state = RuntimeBootstrapState(bindings=_bindings)
    orchestrator = ModuleLifecycleOrchestrator(build_runtime_modules(state))

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
        _runtime_orchestrator = None
        _runtime_state = None
        return
    except Exception as exc:
        logger.error("Failed to initialize agent runtime: %s", exc, exc_info=True)
        _runtime_orchestrator = None
        _runtime_state = None
        raise

    _runtime_orchestrator = orchestrator
    _runtime_state = state
    logger.info("Agent runtime initialized successfully")


async def shutdown_agent_runtime() -> None:
    """Shutdown agent runtime."""
    global _runtime_orchestrator, _runtime_state

    try:
        if _runtime_orchestrator is not None:
            await _runtime_orchestrator.shutdown()
    except Exception as exc:
        logger.error("Failed to stop agent runtime: %s", exc, exc_info=True)
    finally:
        _runtime_orchestrator = None
        _runtime_state = None
        logger.info("Agent runtime stopped")


async def initialize_chat_agent() -> None:
    """Backward-compatible runtime initialization entrypoint."""
    await initialize_agent_runtime()


async def shutdown_chat_agent() -> None:
    """Backward-compatible runtime shutdown entrypoint."""
    await shutdown_agent_runtime()
