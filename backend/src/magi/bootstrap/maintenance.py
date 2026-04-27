"""Bootstrap maintenance module for remaining infrastructure dependencies."""

from __future__ import annotations

from ..config import get_config
from .lifecycle import LifecycleModule
from .context import RuntimeBootstrapContext, require_initialized
from ..core.maintenance import MaintenanceConfig, MaintenanceDaemon, set_maintenance_daemon
from ..core.logger import get_logger

logger = get_logger(__name__)


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
        unified_memory = require_initialized(self._context.memory.unified_memory, "unified memory")

        async def _run_memory_maintenance() -> dict[str, int]:
            memory_settings = get_config().agent.memory
            return await unified_memory.run_maintenance(
                retention_days=memory_settings.retention_days,
                history_behavior=getattr(memory_settings.history_behavior, "value", str(memory_settings.history_behavior)),
            )

        maintenance_config = MaintenanceConfig(
            enabled=config.agent.maintenance.enabled,
            interval_seconds=config.agent.maintenance.interval_seconds,
            health_check=config.agent.maintenance.health_check,
            log_rotation_check=config.agent.maintenance.log_rotation_check,
        )
        self._context.maintenance.maintenance_daemon = MaintenanceDaemon(
            config=maintenance_config,
            maintenance_callback=_run_memory_maintenance,
        )
        await self._context.maintenance.maintenance_daemon.start()
        set_maintenance_daemon(self._context.maintenance.maintenance_daemon)
        logger.info("Maintenance daemon started")

    async def shutdown(self) -> None:
        if self._context.maintenance.maintenance_daemon is not None:
            await self._context.maintenance.maintenance_daemon.stop()
            self._context.maintenance.maintenance_daemon = None
        set_maintenance_daemon(None)
