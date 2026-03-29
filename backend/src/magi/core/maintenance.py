"""
Maintenance daemon for background cleanup and health tasks.

This module provides a background daemon that performs:
- System health checks
- Log rotation checks
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

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
    interval_seconds: float = 300.0
    health_check: bool = True
    log_rotation_check: bool = True


class MaintenanceDaemon:
    """Background daemon for system maintenance tasks."""

    def __init__(
        self,
        config: Optional[MaintenanceConfig] = None,
        health_check_callback: Optional[Callable[[], dict[str, Any]]] = None,
    ) -> None:
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
        logger.info("Maintenance daemon started (interval: %ss)", self.config.interval_seconds)

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
        while self._running:
            try:
                await asyncio.sleep(self.config.interval_seconds)
                await self._run_maintenance()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Maintenance run failed: %s", exc, exc_info=True)
                self._stats.errors += 1

    async def _run_maintenance(self) -> None:
        start_time = time.time()
        logger.debug("Starting maintenance run")
        try:
            if self.config.health_check:
                await self._run_health_checks()
            if self.config.log_rotation_check:
                await self._check_log_rotation()

            self._stats.runs_completed += 1
            self._stats.last_run_time = start_time
            self._stats.last_run_duration_ms = (time.time() - start_time) * 1000
            logger.debug("Maintenance run completed in %.1fms", self._stats.last_run_duration_ms)
        except Exception as exc:
            logger.error("Maintenance task error: %s", exc)
            self._stats.errors += 1
            raise

    async def _run_health_checks(self) -> None:
        try:
            health_status = {
                "timestamp": time.time(),
            }
            if self.health_check_callback:
                custom_health = self.health_check_callback()
                if asyncio.iscoroutine(custom_health):
                    custom_health = await custom_health
                health_status["custom"] = custom_health

            issues: list[str] = []

            if issues:
                logger.warning("Health check issues: %s", issues)
                self._stats.health_checks_failed += 1
            else:
                self._stats.health_checks_passed += 1
        except Exception as exc:
            logger.error("Health check failed: %s", exc)
            self._stats.health_checks_failed += 1

    async def _check_log_rotation(self) -> None:
        try:
            from ..utils.runtime import get_runtime_paths

            runtime_paths = get_runtime_paths()
            logs_dir = runtime_paths.logs_dir
            if not logs_dir.exists():
                return

            max_log_size_mb = 100
            for log_file in logs_dir.glob("*.log"):
                size_mb = log_file.stat().st_size / (1024 * 1024)
                if size_mb > max_log_size_mb:
                    logger.warning(
                        "Log file %s is large (%.1fMB), consider rotation",
                        log_file.name,
                        size_mb,
                    )
        except Exception as exc:
            logger.debug("Log rotation check skipped: %s", exc)

    def get_stats(self) -> dict[str, Any]:
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


_maintenance_daemon: MaintenanceDaemon | None = None


def get_maintenance_daemon() -> MaintenanceDaemon | None:
    """Get the global maintenance daemon instance."""

    return _maintenance_daemon


def set_maintenance_daemon(daemon: MaintenanceDaemon | None) -> None:
    """Set or clear the global maintenance daemon instance."""

    global _maintenance_daemon
    _maintenance_daemon = daemon
