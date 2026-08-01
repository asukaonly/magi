"""Bootstrap maintenance module for remaining infrastructure dependencies."""

from __future__ import annotations

from ..chat.asset_gc import ChatAssetGC
from magi.core.chat_assets.mutations import run_chat_asset_mutation
from ..config import get_config
from .lifecycle import LifecycleModule
from .context import RuntimeBootstrapContext, require_initialized
from ..core.maintenance import MaintenanceConfig, MaintenanceDaemon, set_maintenance_daemon
from ..core.runtime_operational_gc import RuntimeOperationalGC
from ..core.logger import get_logger
from ..scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ..scheduler.service import SchedulerService
from ..utils.runtime import get_runtime_paths

logger = get_logger(__name__)

SCHEDULE_ID_RUNTIME_OPERATIONAL_GC = "runtime-operational-gc:global"
TARGET_KEY_RUNTIME_OPERATIONAL_GC = "runtime_operational_gc"


class RuntimeOperationalGCScheduleContrib:
    """Register runtime operational cleanup with the persistent scheduler."""

    def __init__(
        self,
        *,
        unified_memory,
        llm_usage_store,
        get_config_func=get_config,
        runtime_paths_provider=get_runtime_paths,
    ) -> None:
        self._unified_memory = unified_memory
        self._llm_usage_store = llm_usage_store
        self._get_config = get_config_func
        self._runtime_paths_provider = runtime_paths_provider

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(
            ScheduledTargetType.RUNTIME_OPERATIONAL_GC,
            self.handle,
        )
        config = self._get_config()
        maintenance = config.agent.maintenance
        if not maintenance.enabled:
            await scheduler.unschedule(
                SCHEDULE_ID_RUNTIME_OPERATIONAL_GC,
                target_type=ScheduledTargetType.RUNTIME_OPERATIONAL_GC,
                target_key=TARGET_KEY_RUNTIME_OPERATIONAL_GC,
            )
            return
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_RUNTIME_OPERATIONAL_GC,
            target_type=ScheduledTargetType.RUNTIME_OPERATIONAL_GC,
            target_key=TARGET_KEY_RUNTIME_OPERATIONAL_GC,
            seconds=float(maintenance.interval_seconds),
            target_payload={},
        )

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_RUNTIME_OPERATIONAL_GC,
            target_type=ScheduledTargetType.RUNTIME_OPERATIONAL_GC,
            target_key=TARGET_KEY_RUNTIME_OPERATIONAL_GC,
        )

    async def handle(
        self,
        context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        _ = context
        try:
            current_config = self._get_config()
            runtime_paths = self._runtime_paths_provider()
            results = await self._unified_memory.cleanup_runtime_data()
            runtime_gc = RuntimeOperationalGC(
                lifecycle=current_config.lifecycle,
                llm_usage_store=self._llm_usage_store,
                runtime_paths=runtime_paths,
            )
            results.update(await runtime_gc.run())
            chat_asset_gc = ChatAssetGC(runtime_paths=runtime_paths)
            results.update(
                await run_chat_asset_mutation(
                    chat_asset_gc.sweep_orphan_assets,
                    orphan_grace_hours=(current_config.lifecycle.chat_assets.orphan_grace_hours),
                    delete_orphan_sessions=(
                        current_config.lifecycle.chat_assets.delete_on_session_delete
                    ),
                )
            )
        except Exception as exc:
            logger.warning("runtime operational gc failed", error=str(exc), exc_info=True)
            return ScheduledExecutionResult(
                success=False,
                message="runtime_operational_gc_failed",
                stats={"error": str(exc)},
            )
        return ScheduledExecutionResult(
            success=True,
            message="runtime_operational_gc_ok",
            stats=results,
        )


class RuntimeOperationalGCScheduleRegistrationModule(LifecycleModule):
    """Register runtime operational cleanup as a scheduler-owned task."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_operational_gc_scheduler",
            dependencies=("runtime_scheduler", "runtime_configuration", "runtime_memory"),
        )
        self._context = context
        self._contrib: RuntimeOperationalGCScheduleContrib | None = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Operational GC schedule held for full-clear recovery")
            return
        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service,
            "scheduler service",
        )
        unified_memory = require_initialized(
            self._context.memory.unified_memory,
            "unified memory",
        )
        llm_usage_store = require_initialized(
            self._context.llm.llm_usage_store,
            "LLM usage store",
        )
        self._contrib = RuntimeOperationalGCScheduleContrib(
            unified_memory=unified_memory,
            llm_usage_store=llm_usage_store,
        )
        await self._contrib.register_schedules(scheduler_service)
        logger.info("Runtime operational GC schedule registered")

    async def shutdown(self) -> None:
        if self._contrib is not None and self._context.scheduler.scheduler_service is not None:
            await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._contrib = None


class OtherDependenciesModule(LifecycleModule):
    """Initialize remaining runtime dependencies (maintenance daemon)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_other_dependencies",
            dependencies=("runtime_scheduler", "runtime_configuration", "runtime_memory"),
        )
        self._context = context

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")

        maintenance_config = MaintenanceConfig(
            enabled=config.agent.maintenance.enabled,
            interval_seconds=config.agent.maintenance.interval_seconds,
            health_check=config.agent.maintenance.health_check,
            log_rotation_check=config.agent.maintenance.log_rotation_check,
        )
        self._context.maintenance.maintenance_daemon = MaintenanceDaemon(
            config=maintenance_config,
        )
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Maintenance daemon held for full-clear recovery")
            return
        await self._context.maintenance.maintenance_daemon.start()
        set_maintenance_daemon(self._context.maintenance.maintenance_daemon)
        logger.info("Maintenance daemon started")

    async def shutdown(self) -> None:
        if self._context.maintenance.maintenance_daemon is not None:
            await self._context.maintenance.maintenance_daemon.stop()
            self._context.maintenance.maintenance_daemon = None
        set_maintenance_daemon(None)
