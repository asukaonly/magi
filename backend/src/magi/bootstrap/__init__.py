"""Bootstrap package for backend runtime composition and lifecycle orchestration."""

from __future__ import annotations

from .context import (
    RuntimeBootstrapContext,
    require_initialized,
    CoreBootstrapState,
    LLMBootstrapState,
    RuntimeCommandBootstrapState,
    MessageBusBootstrapState,
    MemoryBootstrapState,
    PersonalityBootstrapState,
    ContextBootstrapState,
    AgentRuntimeBootstrapState,
    TimelineBootstrapState,
    SchedulerBootstrapState,
    MaintenanceBootstrapState,
)
from .lifecycle import (
    LifecycleModule,
    ModuleLifecycleOrchestrator,
)

__all__ = [
    # Context
    "RuntimeBootstrapContext",
    "require_initialized",
    "CoreBootstrapState",
    "LLMBootstrapState",
    "RuntimeCommandBootstrapState",
    "MessageBusBootstrapState",
    "MemoryBootstrapState",
    "PersonalityBootstrapState",
    "ContextBootstrapState",
    "AgentRuntimeBootstrapState",
    "TimelineBootstrapState",
    "SchedulerBootstrapState",
    "MaintenanceBootstrapState",
    # Lifecycle
    "LifecycleModule",
    "ModuleLifecycleOrchestrator",
    # Builder
    "build_runtime_modules",
    # Backend entrypoints
    "initialize_agent_runtime",
    "shutdown_agent_runtime",
    "refresh_runtime_llm_config",
]


def __getattr__(name: str):
    """Lazily expose builder and backend entrypoints to avoid import cycles."""

    if name == "build_runtime_modules":
        from .builder import build_runtime_modules

        return build_runtime_modules

    if name in {
        "initialize_agent_runtime",
        "shutdown_agent_runtime",
        "refresh_runtime_llm_config",
    }:
        from . import backend as _backend

        return getattr(_backend, name)

    raise AttributeError(name)
