"""Host coordinator for plugin- and sensor-owned user-content deletion."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
import inspect
from typing import Any, Literal

from magi_plugin_sdk import UserContentClearContext, UserContentClearRequest
from magi_plugin_sdk.channels import (
    ChannelInboundClearRequest,
    ChannelInboundClearStrategy,
)
from magi_plugin_sdk.sensors import PluginRuntimePaths

from ..core.logger import get_logger
from .manager import PluginManager, PluginUserContentTargetSnapshot
from .operation_execution import plugin_user_content_clear_boundary
from .user_content_clear_checkpoint import PluginUserContentClearCheckpointStore

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PluginUserContentClearFailure:
    """One failed plugin or sensor clear hook."""

    target_kind: Literal["plugin", "sensor", "channel"]
    plugin_id: str
    sensor_id: str | None
    error_type: str
    error: str
    channel_type: str | None = None


@dataclass(frozen=True, slots=True)
class PluginUserContentClearReport:
    """Aggregate outcome after every snapshotted hook was attempted."""

    clear_generation: int
    attempted: int
    cleared: int
    failures: tuple[PluginUserContentClearFailure, ...]


class PluginUserContentClearError(RuntimeError):
    """Raised after all clear hooks run when one or more hooks failed."""

    def __init__(
        self,
        report: PluginUserContentClearReport,
        causes: tuple[Exception, ...],
    ) -> None:
        self.report = report
        self.causes = causes
        targets = ", ".join(
            (
                f"sensor:{failure.plugin_id}/{failure.sensor_id}"
                if failure.sensor_id is not None
                else (
                    f"channel:{failure.plugin_id}/{failure.channel_type}"
                    if failure.channel_type is not None
                    else f"plugin:{failure.plugin_id}"
                )
            )
            for failure in report.failures
        )
        super().__init__(f"Plugin user-content clear failed for: {targets}")


class PluginUserContentClearRecoveryError(RuntimeError):
    """Report a clear finalization failure without hiding the clear failure."""

    def __init__(
        self,
        *,
        clear_error: BaseException | None,
        recovery_error: BaseException,
        quiesce_error: BaseException | None = None,
    ) -> None:
        self.clear_error = clear_error
        self.recovery_error = recovery_error
        self.quiesce_error = quiesce_error
        super().__init__("Plugin user-content clear could not be finalized safely")


class PluginUserContentClearSession:
    """One target snapshot held inside the host's exclusive plugin boundary."""

    def __init__(
        self,
        *,
        plugin_manager: PluginManager,
        targets: PluginUserContentTargetSnapshot,
        runtime_paths: PluginRuntimePaths,
        checkpoint_store: PluginUserContentClearCheckpointStore,
        read_current_clear_generation: Callable[[], Awaitable[int]],
        hook_timeout_seconds: float,
    ) -> None:
        self._plugin_manager = plugin_manager
        self._targets = targets
        self._runtime_paths = runtime_paths
        self._checkpoint_store = checkpoint_store
        self._read_current_clear_generation = read_current_clear_generation
        self._hook_timeout_seconds = hook_timeout_seconds
        self._active = True
        self._completed_generation: int | None = None
        self._completed_report: PluginUserContentClearReport | None = None
        self._previous_applied_generation: int | None = None
        self._released_temporary_plugin_ids: set[str] = set()
        self._surrounding_failure: BaseException | None = None

    async def close(self) -> tuple[PluginUserContentClearFailure, ...]:
        """Release instances loaded only for disabled-plugin deletion."""

        self._active = False
        failures, _causes = await self._release_temporary_plugins()
        return tuple(failures)

    @property
    def completed_generation(self) -> int | None:
        """Return the generation whose hooks completed inside this session."""

        return self._completed_generation

    @property
    def surrounding_failure(self) -> BaseException | None:
        """Return a later full-clear failure recorded before boundary exit."""

        return self._surrounding_failure

    def mark_surrounding_clear_failed(self, error: BaseException) -> None:
        """Prevent checkpoint commit when a later global clearer fails."""

        if self._surrounding_failure is None:
            self._surrounding_failure = error

    async def clear_user_content(
        self,
        request: UserContentClearRequest,
    ) -> PluginUserContentClearReport:
        """Run every captured hook and aggregate failures after all attempts."""

        if not self._active:
            raise RuntimeError("Plugin user-content clear session is no longer active")

        current_generation = await self._read_current_clear_generation()
        if request.clear_generation != current_generation:
            raise RuntimeError(
                "Plugin user-content clear request does not match the shared clear generation"
            )
        applied_generation = await self._checkpoint_store.read_applied_generation()
        if applied_generation > current_generation:
            raise RuntimeError(
                "Plugin user-content clear checkpoint is ahead of the shared generation"
            )
        if applied_generation == request.clear_generation:
            return PluginUserContentClearReport(
                clear_generation=request.clear_generation,
                attempted=0,
                cleared=0,
                failures=(),
            )
        if self._completed_generation == request.clear_generation:
            assert self._completed_report is not None
            return self._completed_report

        attempted = 0
        cleared = 0
        failures: list[PluginUserContentClearFailure] = []
        causes: list[Exception] = []

        for preparation_failure in self._targets.preparation_failures:
            attempted += 1
            cause = preparation_failure.error
            failures.append(
                PluginUserContentClearFailure(
                    target_kind="plugin",
                    plugin_id=preparation_failure.plugin_id,
                    sensor_id=None,
                    error_type=cause.__class__.__name__,
                    error=str(cause) or cause.__class__.__name__,
                )
            )
            causes.append(cause)

        settings_by_plugin_id = {
            plugin_id: settings for plugin_id, _plugin, settings in self._targets.plugins
        }

        for plugin_id, plugin, plugin_settings in self._targets.plugins:
            attempted += 1
            context = UserContentClearContext(
                request=request,
                runtime_paths=self._runtime_paths,
                plugin_id=plugin_id,
                plugin_settings=plugin_settings,
            )
            failure = await self._run_hook(
                target_kind="plugin",
                plugin_id=plugin_id,
                sensor_id=None,
                hook=plugin.clear_user_content,
                context=context,
            )
            if failure is None:
                cleared += 1
            else:
                failure_record, cause = failure
                failures.append(failure_record)
                causes.append(cause)

        for sensor_target in self._targets.sensors:
            attempted += 1
            context = UserContentClearContext(
                request=request,
                runtime_paths=self._runtime_paths,
                plugin_id=sensor_target.plugin_id,
                sensor_id=sensor_target.sensor_id,
                plugin_settings=settings_by_plugin_id.get(
                    sensor_target.plugin_id,
                    {},
                ),
            )
            hook = getattr(sensor_target.sensor, "clear_user_content", None)
            if not callable(hook):
                failure = (
                    PluginUserContentClearFailure(
                        target_kind="sensor",
                        plugin_id=sensor_target.plugin_id,
                        sensor_id=sensor_target.sensor_id,
                        error_type="TypeError",
                        error="Registered sensor does not implement clear_user_content",
                    ),
                    TypeError("Registered sensor does not implement clear_user_content"),
                )
            else:
                failure = await self._run_hook(
                    target_kind="sensor",
                    plugin_id=sensor_target.plugin_id,
                    sensor_id=sensor_target.sensor_id,
                    hook=hook,
                    context=context,
                )
            if failure is None:
                cleared += 1
            else:
                failure_record, cause = failure
                failures.append(failure_record)
                causes.append(cause)

        for channel_target in self._targets.channels:
            attempted += 1
            failure = await self._run_channel_clear(
                plugin_id=channel_target.plugin_id,
                channel_type=channel_target.channel_type,
                channel=channel_target.channel,
                request=request,
            )
            if failure is None:
                cleared += 1
            else:
                failure_record, cause = failure
                failures.append(failure_record)
                causes.append(cause)

        release_failures, release_causes = await self._release_temporary_plugins()
        attempted += len(self._targets.temporary_plugin_ids)
        cleared += len(self._targets.temporary_plugin_ids) - len(release_failures)
        failures.extend(release_failures)
        causes.extend(release_causes)

        report = PluginUserContentClearReport(
            clear_generation=request.clear_generation,
            attempted=attempted,
            cleared=cleared,
            failures=tuple(failures),
        )
        if failures:
            raise PluginUserContentClearError(report, tuple(causes)) from causes[0]
        self._completed_generation = request.clear_generation
        self._completed_report = report
        self._previous_applied_generation = applied_generation
        return report

    async def commit_completed_generation(self) -> None:
        """Persist a successful hook pass after the surrounding clear succeeds."""

        if self._completed_generation is None:
            return
        await self._checkpoint_store.mark_applied(self._completed_generation)

    async def restore_completed_generation_pending(self) -> None:
        """Restore the prior checkpoint if a paused executor cannot resume."""

        if self._completed_generation is None or self._previous_applied_generation is None:
            return
        await self._checkpoint_store.restore_pending(
            clear_generation=self._completed_generation,
            previous_applied_generation=self._previous_applied_generation,
        )

    async def _release_temporary_plugins(
        self,
    ) -> tuple[list[PluginUserContentClearFailure], list[Exception]]:
        failures: list[PluginUserContentClearFailure] = []
        causes: list[Exception] = []
        released = self._released_temporary_plugin_ids
        plugins_by_id = {
            plugin_id: plugin for plugin_id, plugin, _settings in self._targets.plugins
        }
        for plugin_id in sorted(self._targets.temporary_plugin_ids - released):
            plugin = plugins_by_id[plugin_id]
            try:
                result = plugin.shutdown()
                if inspect.isawaitable(result):
                    await asyncio.wait_for(
                        result,
                        timeout=self._hook_timeout_seconds,
                    )
            except Exception as exc:
                failures.append(
                    PluginUserContentClearFailure(
                        target_kind="plugin",
                        plugin_id=plugin_id,
                        sensor_id=None,
                        error_type=exc.__class__.__name__,
                        error=str(exc) or exc.__class__.__name__,
                    )
                )
                causes.append(exc)
            finally:
                try:
                    self._plugin_manager.release_temporary_user_content_clear_target(plugin_id)
                except Exception as exc:
                    failures.append(
                        PluginUserContentClearFailure(
                            target_kind="plugin",
                            plugin_id=plugin_id,
                            sensor_id=None,
                            error_type=exc.__class__.__name__,
                            error=str(exc) or exc.__class__.__name__,
                        )
                    )
                    causes.append(exc)
                released.add(plugin_id)
        return failures, causes

    async def has_pending_generation(self) -> bool:
        """Return whether the shared generation still needs a full hook pass."""

        current_generation = await self._read_current_clear_generation()
        applied_generation = await self._checkpoint_store.read_applied_generation()
        if applied_generation > current_generation:
            raise RuntimeError(
                "Plugin user-content clear checkpoint is ahead of the shared generation"
            )
        return applied_generation < current_generation

    async def _run_hook(
        self,
        *,
        target_kind: Literal["plugin", "sensor"],
        plugin_id: str,
        sensor_id: str | None,
        hook: Callable[[UserContentClearContext], Any],
        context: UserContentClearContext,
    ) -> tuple[PluginUserContentClearFailure, Exception] | None:
        try:
            result = hook(context)
            if not asyncio.iscoroutine(result):
                raise TypeError("clear_user_content must be async")
            await asyncio.wait_for(result, timeout=self._hook_timeout_seconds)
            return None
        except Exception as exc:
            error_text = str(exc) or (
                f"Timed out after {self._hook_timeout_seconds:g} seconds"
                if isinstance(exc, asyncio.TimeoutError)
                else exc.__class__.__name__
            )
            logger.exception(
                "Plugin user-content clear hook failed",
                target_kind=target_kind,
                plugin_id=plugin_id,
                sensor_id=sensor_id,
                clear_generation=context.request.clear_generation,
            )
            return (
                PluginUserContentClearFailure(
                    target_kind=target_kind,
                    plugin_id=plugin_id,
                    sensor_id=sensor_id,
                    error_type=exc.__class__.__name__,
                    error=error_text,
                ),
                exc,
            )

    async def _run_channel_clear(
        self,
        *,
        plugin_id: str,
        channel_type: str,
        channel: Any,
        request: UserContentClearRequest,
    ) -> tuple[PluginUserContentClearFailure, Exception] | None:
        async def clear_channel() -> None:
            strategy = channel.inbound_clear_strategy
            if strategy is ChannelInboundClearStrategy.INTERNAL:
                return
            if strategy not in (
                ChannelInboundClearStrategy.PROVIDER_TIME,
                ChannelInboundClearStrategy.DURABLE_CURSOR,
            ):
                raise TypeError("Plugin channel has no inbound clear strategy")
            async with channel.inbound_clear_boundary(
                ChannelInboundClearRequest(
                    channel_type=channel_type,
                    clear_generation=request.clear_generation,
                )
            ):
                pass

        try:
            await asyncio.wait_for(
                clear_channel(),
                timeout=self._hook_timeout_seconds,
            )
            return None
        except Exception as exc:
            logger.exception(
                "Plugin channel user-content clear failed",
                plugin_id=plugin_id,
                channel_type=channel_type,
                clear_generation=request.clear_generation,
            )
            return (
                PluginUserContentClearFailure(
                    target_kind="channel",
                    plugin_id=plugin_id,
                    sensor_id=None,
                    channel_type=channel_type,
                    error_type=exc.__class__.__name__,
                    error=str(exc) or exc.__class__.__name__,
                ),
                exc,
            )


class PluginUserContentClearCoordinator:
    """Quiesce plugin operations and sensor execution around one full clear."""

    def __init__(
        self,
        *,
        plugin_manager: PluginManager,
        runtime_paths: PluginRuntimePaths,
        get_sensor_sync_executor: Callable[[], Any | None],
        checkpoint_store: PluginUserContentClearCheckpointStore,
        read_current_clear_generation: Callable[[], Awaitable[int]],
        hook_timeout_seconds: float = 10.0,
    ) -> None:
        if hook_timeout_seconds <= 0:
            raise ValueError("hook_timeout_seconds must be positive")
        self._plugin_manager = plugin_manager
        self._runtime_paths = runtime_paths
        self._get_sensor_sync_executor = get_sensor_sync_executor
        self._checkpoint_store = checkpoint_store
        self._read_current_clear_generation = read_current_clear_generation
        self._hook_timeout_seconds = float(hook_timeout_seconds)
        self._suspended_executor: Any | None = None

    @asynccontextmanager
    async def user_content_clear_boundary(
        self,
    ) -> AsyncIterator[PluginUserContentClearSession]:
        """Stop sensor execution and hold an immutable target snapshot."""

        async with plugin_user_content_clear_boundary():
            executor = self._get_sensor_sync_executor()
            executor_was_running = self._executor_needs_restart(executor)
            restart_executor = executor_was_running or (
                executor is not None and executor is self._suspended_executor
            )
            if executor is not None and executor_was_running:
                try:
                    await executor.stop()
                except BaseException:
                    self._suspended_executor = executor
                    raise

            targets = await asyncio.to_thread(
                self._plugin_manager.snapshot_user_content_clear_targets
            )
            session = PluginUserContentClearSession(
                plugin_manager=self._plugin_manager,
                targets=targets,
                runtime_paths=self._runtime_paths,
                checkpoint_store=self._checkpoint_store,
                read_current_clear_generation=self._read_current_clear_generation,
                hook_timeout_seconds=self._hook_timeout_seconds,
            )
            clear_error: BaseException | None = None
            clear_traceback = None
            try:
                yield session
            except BaseException as exc:
                clear_error = exc
                clear_traceback = exc.__traceback__
            finally:
                close_failures = await session.close()
                if close_failures:
                    close_error = RuntimeError(
                        "Temporary plugin cleanup failed for: "
                        + ", ".join(failure.plugin_id for failure in close_failures)
                    )
                    if clear_error is None:
                        clear_error = close_error
                        clear_traceback = close_error.__traceback__
                    else:
                        logger.error(
                            "Temporary plugin cleanup also failed",
                            failures=[failure.plugin_id for failure in close_failures],
                        )

            if clear_error is None and session.surrounding_failure is not None:
                clear_error = session.surrounding_failure
                clear_traceback = clear_error.__traceback__

            recovery_error: BaseException | None = None
            quiesce_error: BaseException | None = None
            if clear_error is None and session.completed_generation is not None:
                if executor is not None and restart_executor:
                    try:
                        await executor.start(paused=True)
                    except BaseException as exc:
                        recovery_error = exc
                if recovery_error is None:
                    try:
                        await session.commit_completed_generation()
                    except BaseException as exc:
                        recovery_error = exc
                        if executor is not None and restart_executor:
                            try:
                                await executor.stop()
                            except BaseException as stop_exc:
                                quiesce_error = stop_exc
                if recovery_error is None and executor is not None and restart_executor:
                    try:
                        executor.resume()
                    except BaseException as exc:
                        recovery_error = exc
                        try:
                            await session.restore_completed_generation_pending()
                        except BaseException as rollback_exc:
                            quiesce_error = rollback_exc
                        try:
                            await executor.stop()
                        except BaseException as stop_exc:
                            if quiesce_error is None:
                                quiesce_error = stop_exc

            pending_generation = True
            try:
                pending_generation = await session.has_pending_generation()
            except BaseException as exc:
                if recovery_error is None and clear_error is None:
                    recovery_error = exc

            if (
                executor is not None
                and restart_executor
                and (clear_error is not None or recovery_error is not None or pending_generation)
            ):
                self._suspended_executor = executor
            elif executor is not None and restart_executor and session.completed_generation is None:
                try:
                    await executor.start()
                    if self._suspended_executor is executor:
                        self._suspended_executor = None
                except BaseException as exc:
                    recovery_error = exc
                    self._suspended_executor = executor
            elif executor is not None and self._suspended_executor is executor:
                self._suspended_executor = None

            if recovery_error is not None:
                raise PluginUserContentClearRecoveryError(
                    clear_error=clear_error,
                    recovery_error=recovery_error,
                    quiesce_error=quiesce_error,
                ) from recovery_error
            if clear_error is not None:
                raise clear_error.with_traceback(clear_traceback)

    async def recover_pending_user_content_clear(
        self,
    ) -> PluginUserContentClearReport | None:
        """Replay an interrupted generation before collection runtimes start."""

        current_generation = await self._read_current_clear_generation()
        applied_generation = await self._checkpoint_store.read_applied_generation()
        if applied_generation > current_generation:
            raise RuntimeError(
                "Plugin user-content clear checkpoint is ahead of the shared generation"
            )
        if applied_generation == current_generation:
            return None
        async with self.user_content_clear_boundary() as session:
            return await session.clear_user_content(
                UserContentClearRequest(
                    clear_generation=current_generation,
                    reason="recover_interrupted_user_clear",
                )
            )

    async def require_no_pending_generation(self) -> None:
        """Fail closed instead of mistaking plugin-only replay for global recovery."""

        if await self.has_pending_generation():
            raise RuntimeError("Interrupted full user-content clear remains pending")

    async def has_pending_generation(self) -> bool:
        """Return whether plugin state still trails the shared full-clear generation."""

        current_generation = await self._read_current_clear_generation()
        applied_generation = await self._checkpoint_store.read_applied_generation()
        if applied_generation > current_generation:
            raise RuntimeError(
                "Plugin user-content clear checkpoint is ahead of the shared generation"
            )
        return applied_generation < current_generation

    @staticmethod
    def _executor_needs_restart(executor: Any | None) -> bool:
        if executor is None:
            return False
        state = getattr(executor, "state", None)
        state_value = getattr(state, "value", state)
        if state_value is None:
            return True
        return str(state_value).lower() != "stopped"


__all__ = [
    "PluginUserContentClearCoordinator",
    "PluginUserContentClearError",
    "PluginUserContentClearFailure",
    "PluginUserContentClearRecoveryError",
    "PluginUserContentClearReport",
    "PluginUserContentClearSession",
]
