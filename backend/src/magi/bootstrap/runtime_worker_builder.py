"""Bootstrap builder for runtime-worker modules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from .context import RuntimeBootstrapContext
from .exports import RuntimeExportsModule
from .control_plane import ControlPlaneModule
from .lifecycle import LifecycleModule
from .maintenance import OtherDependenciesModule, RuntimeOperationalGCScheduleRegistrationModule
from .runtime_tools import RuntimeFirstPartyToolsModule

from ..core.logger import get_logger

logger = get_logger(__name__)

from ..agent.execution.function_calling.headless_factory import (
    build_function_calling_orchestrator,
    build_headless_engine_run_input,
)
from ..agent.lifecycle import AgentRuntimeModule, AgentScheduleRegistrationModule
from ..chat import get_chat_read_service
from ..chat.task_agent.factory import create_chat_agent_factory
from ..awareness.lifecycle import (
    SensorModule,
    SensorScheduleRegistrationModule,
    SensorStateUpdateSubscriberModule,
    SensorSyncExecutorModule,
)
from ..awareness.scheduler_contrib import request_sensor_schedule_refresh
from ..channels.lifecycle import ChannelsModule
from ..outreach.lifecycle import OutreachModule
from ..chat.lifecycle import (
    ChatProjectorModule,
    ChatStoreModule,
    ControlTranscriptSubscriberModule,
)
from ..config.lifecycle import ConfigurationModule
from ..context.lifecycle import ContextModule
from ..core.lifecycle import CoreDependenciesModule
from ..db.lifecycle import DatabaseMigrationModule
from ..events.lifecycle import (
    MessageBusModule,
    PluginIngressProcessorModule,
    RuntimeCommandProcessorModule,
    RuntimeCommandQueueModule,
)
from ..identity.lifecycle import IdentityModule
from ..llm.lifecycle import LLMRuntimeModule, LLMUsageSubscriberModule
from ..location.lifecycle import LocationModule
from ..mcp.lifecycle import MCPModule
from ..memory.lifecycle import (
    L1MaintenanceScheduleRegistrationModule,
    L2DeriveScheduleRegistrationModule,
    L2MaintenanceScheduleRegistrationModule,
    L2ConsolidationScheduleRegistrationModule,
    L3MaintenanceScheduleRegistrationModule,
    L3SummaryScheduleRegistrationModule,
    L4MaintenanceScheduleRegistrationModule,
    MemoryIngestionSubscriberModule,
    MemoryStoreModule,
)
from ..memory.manual_entries.lifecycle import ManualEntriesModule
from ..media.lifecycle import MediaRegistryModule
from ..personality.lifecycle import PersonalityModule
from ..plugins.lifecycle import PluginSystemModule
from ..runtime_trace import RuntimeTraceStore
from ..runtime_trace.lifecycle import RuntimeTraceSubscriberModule
from ..scheduler.lifecycle import SchedulerModule
from ..hooks.lifecycle import HooksModule
from ..skills.lifecycle import SkillsModule
from ..timeline.handler import build_timeline_handler
from ..timeline.lifecycle import (
    KGSubscriberModule,
    TimelineModule,
    TimelineSchedulersModule,
    TimelineSubscriberModule,
)
from ..tools import tool_registry
from ..tools.lifecycle import ToolsModule
from ..user_profile.portrait_projection_scheduler import register_l2_portrait_projection_refresh


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
        # Eagerly register DI binding so readiness and other infra consumers
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


def _build_subprocess_orphan_cleanup_module(
    context: RuntimeBootstrapContext,
) -> LifecycleModule:
    """Sweep stale child processes from prior backend runs.

    Must execute before any module that spawns a long-lived subprocess
    (plugins, MCP servers, code-agent CLIs). The PID registry that backs
    this cleanup is populated by `ManagedSubprocess.spawn(...)` from
    `magi_plugin_sdk.subprocess`.
    """

    async def _init_subprocess_cleanup() -> None:
        # Lazy import: SDK is part of our environment but we avoid loading
        # it at module-import time in case the SDK is installed in a venv
        # path that hasn't been finalized yet.
        from magi_plugin_sdk.subprocess import ManagedSubprocess

        try:
            killed = ManagedSubprocess.cleanup_orphans()
            if killed:
                logger.info(
                    "Subprocess orphan cleanup completed",
                    killed=killed,
                )
        except Exception as exc:  # noqa: BLE001
            # Cleanup is best-effort — never block boot on it.
            logger.warning(
                "Subprocess orphan cleanup failed",
                error=repr(exc),
            )

    return LifecycleModule(
        name="subprocess_orphan_cleanup",
        init=_init_subprocess_cleanup,
    )


def _build_infrastructure_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build the infrastructure-first phase of the runtime worker."""
    return [
        # Must come first — kills any stale children left behind by a
        # previous backend instance (crash, force-quit, kill -9) before
        # plugin / MCP / agent modules start spawning new ones.
        _build_subprocess_orphan_cleanup_module(context),
        CoreDependenciesModule(context),
        # Apply Alembic schema migrations before any store opens a connection.
        # Owned by the db package (db/lifecycle.py); depends on core deps for
        # runtime paths + initialized db files. Splitting this out of
        # CoreDependenciesModule removes the core -> db import cycle.
        DatabaseMigrationModule(context),
        # L1 substrate — identity must initialize right after core so
        # runtime_paths.identity_db_path is available. Channels/api/
        # awareness modules later in the lifecycle pull the resolver
        # off the bootstrap context (no hard dependency edge — identity
        # is L1, everything imports down to it).
        IdentityModule(context),
        ConfigurationModule(context),
        RuntimeCommandQueueModule(context),
        MessageBusModule(context),
        ChatStoreModule(context),
        PluginSystemModule(
            context,
            tool_registry=tool_registry,
            request_sensor_schedule_refresh=request_sensor_schedule_refresh,
        ),
        LLMRuntimeModule(context),
    ]


def _build_stateful_service_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build the stateful services and shared runtime stores phase."""
    return [
        MemoryStoreModule(
            context,
            start_memory_integration=True,
            portrait_projection_refresh_registrar=register_l2_portrait_projection_refresh,
        ),
        MediaRegistryModule(context),  # after memory store so unified_memory.l1 exists
        LocationModule(context),  # owns location pipeline; reads memory.db path directly
        ManualEntriesModule(context),  # owns manual-entry store/asset/weather construction
        MemoryIngestionSubscriberModule(context),
        LLMUsageSubscriberModule(context),
        ChatProjectorModule(context),
        ControlTranscriptSubscriberModule(context),
        _build_runtime_trace_module(context),
        RuntimeTraceSubscriberModule(context),
        HooksModule(context),
        # Host-register first-party runtime tools (e.g. the sub-agent-spawning
        # `agent` tool, which lives at L12 in magi.agent.runtime_tools and so
        # cannot be registered by the L8 core-tools plugin). Declared before
        # ToolsModule and depended on by it, so the `agent` tool is present in
        # the registry by the time ToolsModule configures it.
        RuntimeFirstPartyToolsModule(),
        ToolsModule(context),
        SkillsModule(
            context,
            tool_registry=tool_registry,
            orchestrator_factory=build_function_calling_orchestrator,
            engine_run_input_factory=build_headless_engine_run_input,
        ),
        MCPModule(context),
        PersonalityModule(context),
        SensorModule(context),
        ContextModule(context),
        AgentRuntimeModule(
            context,
            create_chat_agent_factory=create_chat_agent_factory,
            chat_read_service_factory=get_chat_read_service,
            build_timeline_handler=build_timeline_handler,
        ),
    ]


def _build_processing_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build long-running processors and business-facing background services."""
    return [
        RuntimeCommandProcessorModule(context),
        PluginIngressProcessorModule(context),
        TimelineModule(context),
        TimelineSubscriberModule(context),
        KGSubscriberModule(context),
        SensorStateUpdateSubscriberModule(context),
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
        L1MaintenanceScheduleRegistrationModule(context),
        L2MaintenanceScheduleRegistrationModule(context),
        L2ConsolidationScheduleRegistrationModule(context),
        L2DeriveScheduleRegistrationModule(context),
        L3SummaryScheduleRegistrationModule(context),
        L3MaintenanceScheduleRegistrationModule(context),
        L4MaintenanceScheduleRegistrationModule(context),
        TimelineSchedulersModule(context),  # NEW
        RuntimeOperationalGCScheduleRegistrationModule(context),
        OtherDependenciesModule(context),
        ChannelsModule(context),
        OutreachModule(context),
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
