"""Bootstrap package for backend runtime composition and lifecycle orchestration.

This package serves as the outer composition root for the layered architecture,
collecting layer-owned lifecycle modules and providing startup/shutdown entrypoints.

Key exports:
- RuntimeBootstrapContext: Slice-based bootstrap context for layer state
- ModuleLifecycleOrchestrator: Orchestrates module startup/shutdown in dependency order
- build_runtime_modules: Assembles lifecycle modules from owning layers
- initialize_agent_runtime / shutdown_agent_runtime: Application lifecycle entrypoints
"""

from .context import (
    RuntimeBootstrapContext,
    require_initialized,
    CoreBootstrapState,
    LLMBootstrapState,
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
from .builder import build_runtime_modules
from .backend import (
    initialize_agent_runtime,
    shutdown_agent_runtime,
    initialize_chat_agent,
    shutdown_chat_agent,
    get_master_agent,
    get_agent_runtime,
    get_scheduler_service,
    get_unified_memory,
    get_memory_integration,
    refresh_runtime_llm_config,
)

__all__ = [
    # Context
    "RuntimeBootstrapContext",
    "require_initialized",
    "CoreBootstrapState",
    "LLMBootstrapState",
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
    "initialize_chat_agent",
    "shutdown_chat_agent",
    "get_master_agent",
    "get_agent_runtime",
    "get_scheduler_service",
    "get_unified_memory",
    "get_memory_integration",
    "refresh_runtime_llm_config",
]
