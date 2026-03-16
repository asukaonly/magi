"""Bootstrap maintenance module for remaining infrastructure dependencies."""

from __future__ import annotations

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
            dependencies=("runtime_scheduler", "runtime_message_bus", "runtime_configuration"),
        )
        self._context = context

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")
        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")

        maintenance_config = MaintenanceConfig(
            enabled=config.agent.maintenance.enabled,
            interval_seconds=config.agent.maintenance.interval_seconds,
            message_cleanup=config.agent.maintenance.message_cleanup,
            message_retain_hours=config.agent.maintenance.message_retain_hours,
            message_cleanup_batch_size=config.agent.maintenance.message_cleanup_batch_size,
            health_check=config.agent.maintenance.health_check,
            log_rotation_check=config.agent.maintenance.log_rotation_check,
        )
        self._context.maintenance.maintenance_daemon = MaintenanceDaemon(
            message_bus=message_bus,
            config=maintenance_config,
        )
        await self._context.maintenance.maintenance_daemon.start()
        set_maintenance_daemon(self._context.maintenance.maintenance_daemon)
        logger.info("Maintenance daemon started")

    async def shutdown(self) -> None:
        if self._context.maintenance.maintenance_daemon is not None:
            await self._context.maintenance.maintenance_daemon.stop()
            self._context.maintenance.maintenance_daemon = None
        set_maintenance_daemon(None)
