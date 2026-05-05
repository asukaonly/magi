"""Bootstrap builder for runtime-worker modules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from .context import RuntimeBootstrapContext
from .exports import RuntimeExportsModule
from .control_plane import ControlPlaneModule
from .lifecycle import LifecycleModule
from .maintenance import OtherDependenciesModule

from ..agent.lifecycle import AgentRuntimeModule, AgentScheduleRegistrationModule
from ..awareness.lifecycle import (
    SensorModule,
    SensorScheduleRegistrationModule,
    SensorSyncExecutorModule,
)
from ..channels.lifecycle import ChannelsModule
from ..chat.lifecycle import ChatProjectorModule, ChatStoreModule
from ..config.lifecycle import ConfigurationModule
from ..context.lifecycle import ContextModule
from ..core.lifecycle import CoreDependenciesModule
from ..events.lifecycle import (
    MessageBusModule,
    PluginIngressProcessorModule,
    RuntimeCommandProcessorModule,
    RuntimeCommandQueueModule,
)
from ..llm.lifecycle import LLMRuntimeModule
from ..mcp.lifecycle import MCPModule
from ..memory.lifecycle import (
    L2MaintenanceScheduleRegistrationModule,
    L3SummaryScheduleRegistrationModule,
    MemoryIngestionSubscriberModule,
    MemoryStoreModule,
)
from ..personality.lifecycle import PersonalityModule
from ..plugins.lifecycle import PluginSystemModule
from ..runtime_trace import RuntimeTraceStore
from ..scheduler.lifecycle import SchedulerModule
from ..skills.lifecycle import SkillsModule
from ..timeline.lifecycle import TimelineModule
from ..tools.lifecycle import ToolsModule


RuntimeWorkerPhaseBuilder = Callable[[RuntimeBootstrapContext], list[LifecycleModule]]


@dataclass(frozen=True, slots=True)
class RuntimeWorkerPhaseDefinition:
    """Describes one ordered phase in the runtime-worker startup plan."""

    phase_id: str
    title: str
    description: str
    module_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RuntimeWorkerPhaseSpec:
    """Private phase spec used to construct modules and public metadata."""

    phase_id: str
    title: str
    description: str
    build_modules: RuntimeWorkerPhaseBuilder


def _build_runtime_trace_module(context: RuntimeBootstrapContext) -> LifecycleModule:
    async def _init_runtime_trace() -> None:
        from dependency_injector import providers as di_providers
        from ..core.container import get_container

        runtime_paths = context.core.runtime_paths
        if runtime_paths is None:
            raise RuntimeError("runtime paths is not initialized")
        store = RuntimeTraceStore(db_path=str(runtime_paths.runtime_trace_db_path))
        await store.initialize()
        context.runtime_trace.store = store
        # Eagerly register DI binding so heartbeat and other infra consumers
        # work even when later modules (e.g. LLM) defer initialization.
        get_container().runtime_trace_store.override(di_providers.Object(store))

    async def _shutdown_runtime_trace() -> None:
        from ..core.container import get_container

        get_container().runtime_trace_store.reset_override()
        if context.runtime_trace.store is not None:
            await context.runtime_trace.store.shutdown()
            context.runtime_trace.store = None

    return LifecycleModule(
        name="runtime_trace",
        dependencies=("runtime_core_dependencies",),
        init=_init_runtime_trace,
        shutdown=_shutdown_runtime_trace,
    )


def _build_infrastructure_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build the infrastructure-first phase of the runtime worker."""
    return [
        CoreDependenciesModule(context),
        ConfigurationModule(context),
        RuntimeCommandQueueModule(context),
        MessageBusModule(context),
        ChatStoreModule(context),
        PluginSystemModule(context),
        LLMRuntimeModule(context),
    ]


def _build_stateful_service_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build the stateful services and shared runtime stores phase."""
    return [
        MemoryStoreModule(context, start_memory_integration=True),
        MemoryIngestionSubscriberModule(context),
        ChatProjectorModule(context),
        _build_runtime_trace_module(context),
        ToolsModule(context),
        SkillsModule(context),
        MCPModule(context),
        PersonalityModule(context),
        SensorModule(context),
        ContextModule(context),
        AgentRuntimeModule(context),
    ]


def _build_processing_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build long-running processors and business-facing background services."""
    return [
        RuntimeCommandProcessorModule(context),
        PluginIngressProcessorModule(context),
        TimelineModule(context),
        SchedulerModule(context),
        AgentScheduleRegistrationModule(context),
        SensorScheduleRegistrationModule(context),
        SensorSyncExecutorModule(context),
    ]


def _build_exports_and_maintenance_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build exports, schedule registration, and remaining maintenance modules."""
    return [
        RuntimeExportsModule(context),
        ControlPlaneModule(context),
        L2MaintenanceScheduleRegistrationModule(context),
        L3SummaryScheduleRegistrationModule(context),
        OtherDependenciesModule(context),
        ChannelsModule(context),
    ]


_RUNTIME_WORKER_PHASE_SPECS: tuple[_RuntimeWorkerPhaseSpec, ...] = (
    _RuntimeWorkerPhaseSpec(
        phase_id="infrastructure",
        title="Infrastructure Bring-up",
        description="Core runtime dependencies, configuration, persistence primitives, plugins, and the LLM deferral boundary.",
        build_modules=_build_infrastructure_modules,
    ),
    _RuntimeWorkerPhaseSpec(
        phase_id="stateful_services",
        title="Stateful Services",
        description="Shared stores, tool/skill runtime, personality state, sensors, context assembly, and agent runtime objects.",
        build_modules=_build_stateful_service_modules,
    ),
    _RuntimeWorkerPhaseSpec(
        phase_id="processing",
        title="Processors And Services",
        description="Long-running processors, timeline orchestration, scheduler services, and sensor execution loops.",
        build_modules=_build_processing_modules,
    ),
    _RuntimeWorkerPhaseSpec(
        phase_id="exports_and_maintenance",
        title="Exports And Maintenance",
        description="DI exports, maintenance schedule registration, remaining dependencies, and external channel bindings.",
        build_modules=_build_exports_and_maintenance_modules,
    ),
)


def _build_runtime_worker_phase_entries(
    context: RuntimeBootstrapContext,
) -> tuple[tuple[_RuntimeWorkerPhaseSpec, list[LifecycleModule]], ...]:
    """Build modules grouped by ordered runtime-worker phase."""
    return tuple((spec, spec.build_modules(context)) for spec in _RUNTIME_WORKER_PHASE_SPECS)


@lru_cache(maxsize=1)
def get_runtime_worker_phase_definitions() -> tuple[RuntimeWorkerPhaseDefinition, ...]:
    """Return ordered runtime-worker phase metadata with concrete module names."""
    context = RuntimeBootstrapContext()
    return tuple(
        RuntimeWorkerPhaseDefinition(
            phase_id=spec.phase_id,
            title=spec.title,
            description=spec.description,
            module_names=tuple(module.name for module in modules),
        )
        for spec, modules in _build_runtime_worker_phase_entries(context)
    )


@lru_cache(maxsize=1)
def get_runtime_worker_module_order() -> tuple[str, ...]:
    """Return the flattened runtime-worker startup module order."""
    return tuple(
        module_name
        for phase in get_runtime_worker_phase_definitions()
        for module_name in phase.module_names
    )


@lru_cache(maxsize=1)
def describe_runtime_worker_phase_plan() -> str:
    """Return a human-readable summary of the runtime-worker startup phases."""
    return " | ".join(
        f"{phase.phase_id}={','.join(phase.module_names)}"
        for phase in get_runtime_worker_phase_definitions()
    )


def build_runtime_worker_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build lifecycle modules required by the background runtime worker.

    The returned list stays in exact startup order; the phase helpers only
    make that order easier to understand and maintain.
    """
    return [
        *(
            module
            for _, modules in _build_runtime_worker_phase_entries(context)
            for module in modules
        ),
    ]


__all__ = [
    "RuntimeWorkerPhaseDefinition",
    "build_runtime_worker_modules",
    "describe_runtime_worker_phase_plan",
    "get_runtime_worker_module_order",
    "get_runtime_worker_phase_definitions",
]
