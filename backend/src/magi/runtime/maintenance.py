"""
Maintenance Daemon - Background tasks for system health and cleanup.

This module provides a background daemon that performs:
- Message queue cleanup (completed/failed messages)
- Stale processing message recovery
- System health checks
- Log rotation checks
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class MaintenanceStats:
    """Statistics from maintenance runs."""
    runs_completed: int = 0
    last_run_time: float = 0.0
    last_run_duration_ms: float = 0.0
    messages_cleaned: int = 0
    stale_messages_reset: int = 0
    health_checks_passed: int = 0
    health_checks_failed: int = 0
    errors: int = 0


@dataclass
class MaintenanceConfig:
    """Configuration for maintenance daemon."""
    enabled: bool = True
    interval_seconds: float = 300.0  # 5 minutes
    message_cleanup: bool = True
    message_retain_hours: int = 24
    message_cleanup_batch_size: int = 1000
    health_check: bool = True
    log_rotation_check: bool = True
    stale_processing_timeout_seconds: float = 300.0  # 5 minutes


class MaintenanceDaemon:
    """
    Background daemon for system maintenance tasks.

    Responsibilities:
    1. Clean up old completed/failed messages from queue
    2. Reset stale processing messages (crash recovery)
    3. Perform health checks
    4. Monitor log file sizes
    """

    def __init__(
        self,
        message_bus=None,
        config: Optional[MaintenanceConfig] = None,
        health_check_callback: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        """
        Initialize maintenance daemon.

        Args:
            message_bus: SQLiteMessageBackend instance for queue cleanup
            config: Maintenance configuration
            health_check_callback: Optional callback for custom health checks
        """
        self.message_bus = message_bus
        self.config = config or MaintenanceConfig()
        self.health_check_callback = health_check_callback

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats = MaintenanceStats()

    async def start(self) -> None:
        """Start the maintenance daemon."""
        if not self.config.enabled:
            logger.info("Maintenance daemon is disabled")
            return

        if self._running:
            logger.warning("Maintenance daemon already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Maintenance daemon started (interval: {self.config.interval_seconds}s)")

    async def stop(self) -> None:
        """Stop the maintenance daemon."""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Maintenance daemon stopped")

    async def _run_loop(self) -> None:
        """Main maintenance loop."""
        while self._running:
            try:
                await asyncio.sleep(self.config.interval_seconds)
                await self._run_maintenance()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Maintenance run failed: {e}", exc_info=True)
                self._stats.errors += 1
                # Continue running despite errors

    async def _run_maintenance(self) -> None:
        """Execute all maintenance tasks."""
        start_time = time.time()
        logger.debug("Starting maintenance run...")

        try:
            # 1. Reset stale processing messages
            if self.config.message_cleanup and self.message_bus:
                await self._reset_stale_messages()

            # 2. Clean up old messages
            if self.config.message_cleanup and self.message_bus:
                await self._cleanup_old_messages()

            # 3. Health checks
            if self.config.health_check:
                await self._run_health_checks()

            # 4. Log rotation check
            if self.config.log_rotation_check:
                await self._check_log_rotation()

            # Update stats
            self._stats.runs_completed += 1
            self._stats.last_run_time = start_time
            self._stats.last_run_duration_ms = (time.time() - start_time) * 1000

            logger.debug(f"Maintenance run completed in {self._stats.last_run_duration_ms:.1f}ms")

        except Exception as e:
            logger.error(f"Maintenance task error: {e}")
            self._stats.errors += 1
            raise

    async def _reset_stale_messages(self) -> None:
        """Reset messages stuck in processing state."""
        try:
            count = await self.message_bus.reset_stale_processing_messages(
                timeout_seconds=self.config.stale_processing_timeout_seconds
            )
            if count > 0:
                self._stats.stale_messages_reset += count
        except Exception as e:
            logger.error(f"Failed to reset stale messages: {e}")

    async def _cleanup_old_messages(self) -> None:
        """Clean up old completed/failed messages."""
        try:
            count = await self.message_bus.cleanup_old_messages(
                retain_hours=self.config.message_retain_hours,
                batch_size=self.config.message_cleanup_batch_size,
            )
            if count > 0:
                self._stats.messages_cleaned += count
        except Exception as e:
            logger.error(f"Failed to cleanup old messages: {e}")

    async def _run_health_checks(self) -> None:
        """Run system health checks."""
        try:
            health_status = {
                "timestamp": time.time(),
                "message_queue": await self._check_message_queue_health(),
            }

            # Run custom health check callback if provided
            if self.health_check_callback:
                custom_health = self.health_check_callback()
                if asyncio.iscoroutine(custom_health):
                    custom_health = await custom_health
                health_status["custom"] = custom_health

            # Log any issues
            issues = []
            if health_status.get("message_queue", {}).get("failed", 0) > 100:
                issues.append(f"High failed message count: {health_status['message_queue']['failed']}")

            if issues:
                logger.warning(f"Health check issues: {issues}")
                self._stats.health_checks_failed += 1
            else:
                self._stats.health_checks_passed += 1

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self._stats.health_checks_failed += 1

    async def _check_message_queue_health(self) -> Dict[str, Any]:
        """Check message queue health."""
        if not self.message_bus:
            return {"status": "unavailable"}

        try:
            return await self.message_bus.get_queue_health()
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _check_log_rotation(self) -> None:
        """Check if log files need rotation."""
        try:
            from ..utils.runtime import get_runtime_paths
            runtime_paths = get_runtime_paths()
            logs_dir = runtime_paths.logs_dir

            if not logs_dir.exists():
                return

            # Check log file sizes
            max_log_size_mb = 100  # 100 MB threshold
            for log_file in logs_dir.glob("*.log"):
                size_mb = log_file.stat().st_size / (1024 * 1024)
                if size_mb > max_log_size_mb:
                    logger.warning(f"Log file {log_file.name} is large ({size_mb:.1f}MB), consider rotation")

        except Exception as e:
            logger.debug(f"Log rotation check skipped: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get maintenance statistics."""
        return {
            "enabled": self.config.enabled,
            "running": self._running,
            "interval_seconds": self.config.interval_seconds,
            "runs_completed": self._stats.runs_completed,
            "last_run_time": self._stats.last_run_time,
            "last_run_duration_ms": self._stats.last_run_duration_ms,
            "messages_cleaned": self._stats.messages_cleaned,
            "stale_messages_reset": self._stats.stale_messages_reset,
            "health_checks_passed": self._stats.health_checks_passed,
            "health_checks_failed": self._stats.health_checks_failed,
            "errors": self._stats.errors,
        }


# Global instance
_maintenance_daemon: Optional[MaintenanceDaemon] = None


def get_maintenance_daemon() -> Optional[MaintenanceDaemon]:
    """Get global maintenance daemon instance."""
    return _maintenance_daemon


def set_maintenance_daemon(daemon: MaintenanceDaemon) -> None:
    """Set global maintenance daemon instance."""
    global _maintenance_daemon
    _maintenance_daemon = daemon
