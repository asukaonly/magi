from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.plugins.manager import PluginManager, PluginUserContentTargetSnapshot
from magi.plugins.operation_execution import run_plugin_lifecycle_operation
from magi.plugins.sensors import RegisteredSensorSnapshot, SensorRegistry
from magi.plugins.settings_service import PluginSettingsService
from magi.plugins.user_content_clear import (
    PluginUserContentClearCoordinator,
    PluginUserContentClearError,
    PluginUserContentClearRecoveryError,
)
from magi_plugin_sdk import (
    Plugin,
    PluginSettingsActionResult,
    PluginSettingsActionSpec,
    UserContentClearRequest,
)
from magi_plugin_sdk.channels import ChannelInboundClearStrategy


class _RuntimePaths:
    def plugin_cache_dir(self, plugin_id: str) -> Path:
        return Path("cache") / plugin_id


class _Checkpoint:
    def __init__(
        self,
        applied_generation: int = 0,
        *,
        fail_mark: bool = False,
    ) -> None:
        self.applied_generation = applied_generation
        self.marked: list[int] = []
        self.fail_mark = fail_mark

    async def read_applied_generation(self) -> int:
        return self.applied_generation

    async def mark_applied(self, clear_generation: int) -> None:
        if self.fail_mark:
            raise RuntimeError("checkpoint failed")
        self.applied_generation = clear_generation
        self.marked.append(clear_generation)

    async def restore_pending(
        self,
        *,
        clear_generation: int,
        previous_applied_generation: int,
    ) -> None:
        assert self.applied_generation == clear_generation
        self.applied_generation = previous_applied_generation


class _Manager:
    def __init__(self, snapshot: PluginUserContentTargetSnapshot) -> None:
        self.snapshot = snapshot
        self.snapshot_calls = 0

    def snapshot_user_content_clear_targets(self) -> PluginUserContentTargetSnapshot:
        self.snapshot_calls += 1
        return self.snapshot


class _Executor:
    def __init__(
        self,
        events: list[str],
        *,
        fail_start: bool = False,
        fail_resume: bool = False,
    ) -> None:
        self.events = events
        self.state = SimpleNamespace(value="running")
        self.fail_start = fail_start
        self.fail_resume = fail_resume
        self.paused = False

    async def stop(self) -> None:
        self.events.append("executor-stop")
        self.state = SimpleNamespace(value="stopped")

    async def start(self, *, paused: bool = False) -> None:
        self.events.append("executor-start-paused" if paused else "executor-start")
        if self.fail_start:
            raise RuntimeError("restart failed")
        self.state = SimpleNamespace(value="running")
        self.paused = paused

    def resume(self) -> None:
        self.events.append("executor-resume")
        if self.fail_resume:
            raise RuntimeError("resume failed")
        self.paused = False


class _RecordingPlugin(Plugin):
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        fail: bool = False,
    ) -> None:
        super().__init__()
        self.name = name
        self.events = events
        self.fail = fail
        self.contexts = []

    async def clear_user_content(self, context) -> None:  # type: ignore[no-untyped-def]
        self.contexts.append(context)
        self.events.append(f"plugin:{self.name}")
        if self.fail:
            raise RuntimeError(f"{self.name} failed")


class _RecordingSensor:
    def __init__(self, name: str, events: list[str], *, fail: bool = False) -> None:
        self.name = name
        self.events = events
        self.fail = fail
        self.contexts = []

    async def clear_user_content(self, context) -> None:  # type: ignore[no-untyped-def]
        self.contexts.append(context)
        self.events.append(f"sensor:{self.name}")
        if self.fail:
            raise RuntimeError(f"{self.name} failed")


def _coordinator(
    *,
    snapshot: PluginUserContentTargetSnapshot,
    current_generation: int,
    checkpoint: _Checkpoint,
    executor=None,
) -> PluginUserContentClearCoordinator:
    async def read_generation() -> int:
        return current_generation

    return PluginUserContentClearCoordinator(
        plugin_manager=_Manager(snapshot),  # type: ignore[arg-type]
        runtime_paths=_RuntimePaths(),
        get_sensor_sync_executor=lambda: executor,
        checkpoint_store=checkpoint,  # type: ignore[arg-type]
        read_current_clear_generation=read_generation,
        hook_timeout_seconds=1,
    )


@pytest.mark.asyncio
async def test_clear_attempts_every_plugin_and_sensor_before_reporting_failures() -> None:
    events: list[str] = []
    bad_plugin = _RecordingPlugin("bad", events, fail=True)
    good_plugin = _RecordingPlugin("good", events)
    bad_sensor = _RecordingSensor("bad", events, fail=True)
    good_sensor = _RecordingSensor("good", events)
    snapshot = PluginUserContentTargetSnapshot(
        plugins=(
            ("bad-plugin", bad_plugin, {"account": {"id": "a"}}),
            ("good-plugin", good_plugin, {"enabled": True}),
        ),
        sensors=(
            RegisteredSensorSnapshot("bad-plugin", "sensor.bad", bad_sensor),
            RegisteredSensorSnapshot("good-plugin", "sensor.good", good_sensor),
        ),
    )
    checkpoint = _Checkpoint()
    executor = _Executor(events)
    coordinator = _coordinator(
        snapshot=snapshot,
        current_generation=7,
        checkpoint=checkpoint,
        executor=executor,
    )

    with pytest.raises(PluginUserContentClearError) as raised:
        async with coordinator.user_content_clear_boundary() as session:
            await session.clear_user_content(UserContentClearRequest(7))

    assert events == [
        "executor-stop",
        "plugin:bad",
        "plugin:good",
        "sensor:bad",
        "sensor:good",
    ]
    assert raised.value.report.attempted == 4
    assert raised.value.report.cleared == 2
    assert {
        (failure.target_kind, failure.plugin_id, failure.sensor_id)
        for failure in raised.value.report.failures
    } == {
        ("plugin", "bad-plugin", None),
        ("sensor", "bad-plugin", "sensor.bad"),
    }
    assert checkpoint.applied_generation == 0
    assert executor.state.value == "stopped"

    bad_plugin.fail = False
    bad_sensor.fail = False
    async with coordinator.user_content_clear_boundary() as session:
        retry_report = await session.clear_user_content(UserContentClearRequest(7))

    assert retry_report.cleared == 4
    assert checkpoint.applied_generation == 7
    assert events[-2:] == ["executor-start-paused", "executor-resume"]
    assert executor.state.value == "running"


@pytest.mark.asyncio
async def test_clear_passes_readonly_plugin_settings_to_plugin_and_sensor() -> None:
    events: list[str] = []
    plugin = _RecordingPlugin("example", events)
    sensor = _RecordingSensor("example", events)
    settings = {"sensor": {"watch": True}, "paths": ["/private/source"]}
    snapshot = PluginUserContentTargetSnapshot(
        plugins=(("example", plugin, settings),),
        sensors=(RegisteredSensorSnapshot("example", "sensor.example", sensor),),
    )
    checkpoint = _Checkpoint()
    coordinator = _coordinator(
        snapshot=snapshot,
        current_generation=4,
        checkpoint=checkpoint,
    )

    async with coordinator.user_content_clear_boundary() as session:
        report = await session.clear_user_content(UserContentClearRequest(4))
    settings["sensor"]["watch"] = False

    assert report.attempted == 2
    assert checkpoint.applied_generation == 4
    for context in [*plugin.contexts, *sensor.contexts]:
        assert context.plugin_settings["sensor"]["watch"] is True
        assert context.plugin_settings["paths"] == ("/private/source",)
        assert context.network_access_allowed is False
        assert context.preserve_source_progress is True
    assert sensor.contexts[0].sensor_id == "sensor.example"


@pytest.mark.asyncio
async def test_disabled_installed_plugin_and_sensor_are_cleared_without_enabling() -> None:
    events: list[str] = []
    sensor = _RecordingSensor("disabled", events)

    class _DisabledChannel:
        channel_type = "disabled-channel"
        inbound_clear_strategy = ChannelInboundClearStrategy.PROVIDER_TIME

        @asynccontextmanager
        async def inbound_clear_boundary(self, request):  # type: ignore[no-untyped-def]
            assert request.channel_type == self.channel_type
            assert request.clear_generation == 1
            events.append("channel:enter")
            try:
                yield
            finally:
                events.append("channel:exit")

    channel = _DisabledChannel()

    class _DisabledPlugin(_RecordingPlugin):
        def get_sensors(self):  # type: ignore[no-untyped-def]
            return [("sensor.disabled", sensor, None)]

        def get_channel(self):  # type: ignore[no-untyped-def]
            return channel

        async def shutdown(self) -> None:
            events.append("plugin:shutdown")

    plugin = _DisabledPlugin("disabled", events)
    state = SimpleNamespace(
        manifest=SimpleNamespace(
            kind="plugin",
            plugin_id="disabled",
            source="external",
            plugin_dir="/tmp/disabled",
        ),
        current_settings={"source": {"cursor": "keep"}},
        trusted=True,
        enabled=False,
        loaded=False,
    )
    manager = PluginManager.__new__(PluginManager)
    manager._lifecycle_write_lock = threading.RLock()
    manager._package_states = {"disabled": state}
    manager._plugin_instances = {}
    manager._sensor_registry = SensorRegistry()
    manager._instantiate_plugin = lambda _manifest, _settings: plugin
    checkpoint = _Checkpoint()
    executor = _Executor(events)

    async def read_generation() -> int:
        return 1

    coordinator = PluginUserContentClearCoordinator(
        plugin_manager=manager,
        runtime_paths=_RuntimePaths(),
        get_sensor_sync_executor=lambda: executor,
        checkpoint_store=checkpoint,  # type: ignore[arg-type]
        read_current_clear_generation=read_generation,
        hook_timeout_seconds=1,
    )

    async with coordinator.user_content_clear_boundary() as session:
        report = await session.clear_user_content(UserContentClearRequest(1))

    assert report.failures == ()
    assert "plugin:disabled" in events
    assert "sensor:disabled" in events
    assert "channel:enter" in events
    assert "channel:exit" in events
    assert "plugin:shutdown" in events
    assert state.enabled is False
    assert state.loaded is False
    assert manager._plugin_instances == {}
    assert manager._sensor_registry.list_specs() == []
    assert checkpoint.applied_generation == 1
    assert executor.state.value == "running"


@pytest.mark.asyncio
async def test_broken_disabled_plugin_keeps_clear_pending_and_collection_stopped() -> None:
    events: list[str] = []
    state = SimpleNamespace(
        manifest=SimpleNamespace(
            kind="plugin",
            plugin_id="broken",
            source="external",
            plugin_dir="/tmp/broken",
        ),
        current_settings={},
        trusted=True,
        enabled=False,
        loaded=False,
    )
    manager = PluginManager.__new__(PluginManager)
    manager._lifecycle_write_lock = threading.RLock()
    manager._package_states = {"broken": state}
    manager._plugin_instances = {}
    manager._sensor_registry = SensorRegistry()

    def fail_instantiation(_manifest, _settings):  # type: ignore[no-untyped-def]
        raise ModuleNotFoundError("missing disabled dependency")

    manager._instantiate_plugin = fail_instantiation
    checkpoint = _Checkpoint()
    executor = _Executor(events)

    async def read_generation() -> int:
        return 1

    coordinator = PluginUserContentClearCoordinator(
        plugin_manager=manager,
        runtime_paths=_RuntimePaths(),
        get_sensor_sync_executor=lambda: executor,
        checkpoint_store=checkpoint,  # type: ignore[arg-type]
        read_current_clear_generation=read_generation,
        hook_timeout_seconds=1,
    )

    with pytest.raises(PluginUserContentClearError) as raised:
        async with coordinator.user_content_clear_boundary() as session:
            await session.clear_user_content(UserContentClearRequest(1))

    assert raised.value.report.failures[0].plugin_id == "broken"
    assert checkpoint.applied_generation == 0
    assert executor.state.value == "stopped"
    assert events == ["executor-stop"]
    assert state.enabled is False
    assert state.loaded is False

    repaired_plugin = _RecordingPlugin("repaired", events)
    manager._instantiate_plugin = lambda _manifest, _settings: repaired_plugin
    report = await coordinator.recover_pending_user_content_clear()

    assert report is not None
    assert checkpoint.applied_generation == 1
    assert executor.state.value == "running"
    assert "plugin:repaired" in events
    assert state.enabled is False
    assert state.loaded is False


@pytest.mark.asyncio
async def test_recovery_replays_interrupted_generation_before_executor_exists() -> None:
    events: list[str] = []
    plugin = _RecordingPlugin("recover", events)
    checkpoint = _Checkpoint(applied_generation=2)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(
            plugins=(("recover", plugin, {}),),
            sensors=(),
        ),
        current_generation=3,
        checkpoint=checkpoint,
    )

    report = await coordinator.recover_pending_user_content_clear()

    assert report is not None
    assert report.clear_generation == 3
    assert events == ["plugin:recover"]
    assert checkpoint.marked == [3]
    assert plugin.contexts[0].request.reason == "recover_interrupted_user_clear"


@pytest.mark.asyncio
async def test_recovery_failure_keeps_checkpoint_pending() -> None:
    events: list[str] = []
    plugin = _RecordingPlugin("recover", events, fail=True)
    checkpoint = _Checkpoint(applied_generation=2)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(
            plugins=(("recover", plugin, {}),),
            sensors=(),
        ),
        current_generation=3,
        checkpoint=checkpoint,
    )

    with pytest.raises(PluginUserContentClearError):
        await coordinator.recover_pending_user_content_clear()

    assert checkpoint.applied_generation == 2
    assert checkpoint.marked == []


@pytest.mark.asyncio
async def test_startup_check_does_not_replay_plugin_only_pending_generation() -> None:
    events: list[str] = []
    plugin = _RecordingPlugin("pending", events)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(
            plugins=(("pending", plugin, {}),),
            sensors=(),
        ),
        current_generation=3,
        checkpoint=_Checkpoint(applied_generation=2),
    )

    with pytest.raises(RuntimeError, match="full user-content clear remains pending"):
        await coordinator.require_no_pending_generation()

    assert events == []
    assert plugin.contexts == []


@pytest.mark.asyncio
async def test_completed_generation_is_not_replayed() -> None:
    events: list[str] = []
    plugin = _RecordingPlugin("done", events)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(
            plugins=(("done", plugin, {}),),
            sensors=(),
        ),
        current_generation=5,
        checkpoint=_Checkpoint(applied_generation=5),
    )

    assert await coordinator.recover_pending_user_content_clear() is None
    assert events == []


@pytest.mark.asyncio
async def test_fresh_install_generation_zero_does_not_build_a_clear_request() -> None:
    events: list[str] = []
    plugin = _RecordingPlugin("fresh", events)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(
            plugins=(("fresh", plugin, {}),),
            sensors=(),
        ),
        current_generation=0,
        checkpoint=_Checkpoint(applied_generation=0),
    )

    assert await coordinator.recover_pending_user_content_clear() is None
    assert plugin.contexts == []


@pytest.mark.asyncio
async def test_cancelled_hook_leaves_generation_pending_for_next_startup_replay() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    events: list[str] = []

    class _BlockingPlugin(Plugin):
        async def clear_user_content(self, context) -> None:  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await release.wait()

    plugin = _BlockingPlugin()
    checkpoint = _Checkpoint(applied_generation=1)
    executor = _Executor(events)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(
            plugins=(("blocking", plugin, {}),),
            sensors=(),
        ),
        current_generation=2,
        checkpoint=checkpoint,
        executor=executor,
    )

    async with coordinator.user_content_clear_boundary() as session:
        clear_task = asyncio.create_task(
            session.clear_user_content(UserContentClearRequest(2))
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        clear_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await clear_task

    assert checkpoint.applied_generation == 1
    assert executor.state.value == "stopped"
    assert events == ["executor-stop"]
    report = await coordinator.recover_pending_user_content_clear()
    assert report is not None
    assert calls == 2
    assert checkpoint.applied_generation == 2
    assert executor.state.value == "running"
    assert events == ["executor-stop", "executor-start-paused", "executor-resume"]


@pytest.mark.asyncio
async def test_lifecycle_mutation_waits_until_clear_boundary_reopens() -> None:
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(plugins=(), sensors=()),
        current_generation=1,
        checkpoint=_Checkpoint(),
    )
    mutation_ran = threading.Event()

    async with coordinator.user_content_clear_boundary():
        mutation = asyncio.create_task(
            run_plugin_lifecycle_operation(mutation_ran.set)
        )
        await asyncio.sleep(0.05)
        assert mutation_ran.is_set() is False

    await asyncio.wait_for(mutation, timeout=1)
    assert mutation_ran.is_set() is True


@pytest.mark.asyncio
async def test_clear_waits_for_active_lifecycle_mutation_before_stopping_executor() -> None:
    mutation_started = threading.Event()
    release_mutation = threading.Event()
    events: list[str] = []

    def mutate() -> None:
        mutation_started.set()
        release_mutation.wait(timeout=2)

    mutation = asyncio.create_task(run_plugin_lifecycle_operation(mutate))
    await asyncio.to_thread(mutation_started.wait, 1)
    executor = _Executor(events)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(plugins=(), sensors=()),
        current_generation=1,
        checkpoint=_Checkpoint(applied_generation=1),
        executor=executor,
    )

    async def enter_clear() -> None:
        async with coordinator.user_content_clear_boundary():
            events.append("clear-enter")

    clearing = asyncio.create_task(enter_clear())
    await asyncio.sleep(0.05)
    assert events == []
    release_mutation.set()
    await asyncio.wait_for(mutation, timeout=1)
    await asyncio.wait_for(clearing, timeout=1)

    assert events == ["executor-stop", "clear-enter", "executor-start"]


@pytest.mark.asyncio
async def test_clear_waits_for_active_async_settings_action() -> None:
    action_started = asyncio.Event()
    release_action = asyncio.Event()
    events: list[str] = []

    class _SettingsPlugin(Plugin):
        async def start_settings_action(  # type: ignore[no-untyped-def]
            self,
            action_id,
            *,
            session_id,
            field_values=None,
        ):
            action_started.set()
            await release_action.wait()
            return PluginSettingsActionResult(status="succeeded")

    plugin = _SettingsPlugin()
    service = PluginSettingsService(
        get_package=lambda _plugin_id: None,
        load_plugin=lambda _plugin_id: None,  # type: ignore[arg-type,return-value]
        get_loaded_plugin=lambda _plugin_id: plugin,
        update_plugin_settings=lambda _plugin_id, _settings: None,  # type: ignore[arg-type,return-value]
    )
    spec = PluginSettingsActionSpec(action_id="connect", label="Connect")
    service._resolve_settings_action = lambda _plugin_id, _action_id: (  # type: ignore[method-assign]
        spec,
        plugin,
    )
    executor = _Executor(events)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(plugins=(), sensors=()),
        current_generation=1,
        checkpoint=_Checkpoint(applied_generation=1),
        executor=executor,
    )

    action = asyncio.create_task(
        service.start_plugin_settings_action("settings", "connect")
    )
    await asyncio.wait_for(action_started.wait(), timeout=1)

    async def enter_clear() -> None:
        async with coordinator.user_content_clear_boundary():
            events.append("clear-enter")

    clearing = asyncio.create_task(enter_clear())
    await asyncio.sleep(0.05)
    assert events == []

    release_action.set()
    await asyncio.wait_for(action, timeout=1)
    await asyncio.wait_for(clearing, timeout=1)

    assert events == ["executor-stop", "clear-enter", "executor-start"]


@pytest.mark.asyncio
async def test_failure_after_hooks_keeps_executor_stopped_and_checkpoint_pending() -> None:
    events: list[str] = []
    plugin = _RecordingPlugin("good", events)
    checkpoint = _Checkpoint()
    executor = _Executor(events)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(
            plugins=(("good", plugin, {}),),
            sensors=(),
        ),
        current_generation=1,
        checkpoint=checkpoint,
        executor=executor,
    )

    with pytest.raises(ValueError, match="global clear failed"):
        async with coordinator.user_content_clear_boundary() as session:
            await session.clear_user_content(UserContentClearRequest(1))
            raise ValueError("global clear failed after plugin cleanup")

    assert checkpoint.applied_generation == 0
    assert executor.state.value == "stopped"
    assert events == ["executor-stop", "plugin:good"]


@pytest.mark.asyncio
async def test_recorded_later_clear_failure_prevents_checkpoint_and_resume() -> None:
    events: list[str] = []
    plugin = _RecordingPlugin("good", events)
    checkpoint = _Checkpoint()
    executor = _Executor(events)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(
            plugins=(("good", plugin, {}),),
            sensors=(),
        ),
        current_generation=1,
        checkpoint=checkpoint,
        executor=executor,
    )
    later_failure = RuntimeError("diagnostic logs remain")

    with pytest.raises(RuntimeError, match="diagnostic logs remain"):
        async with coordinator.user_content_clear_boundary() as session:
            await session.clear_user_content(UserContentClearRequest(1))
            session.mark_surrounding_clear_failed(later_failure)

    assert checkpoint.applied_generation == 0
    assert executor.state.value == "stopped"
    assert events == ["executor-stop", "plugin:good"]


@pytest.mark.asyncio
async def test_restart_failure_keeps_executor_stopped_and_checkpoint_pending() -> None:
    events: list[str] = []
    plugin = _RecordingPlugin("good", events)
    checkpoint = _Checkpoint()
    executor = _Executor(events, fail_start=True)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(
            plugins=(("good", plugin, {}),),
            sensors=(),
        ),
        current_generation=1,
        checkpoint=checkpoint,
        executor=executor,
    )

    with pytest.raises(PluginUserContentClearRecoveryError) as raised:
        async with coordinator.user_content_clear_boundary() as session:
            await session.clear_user_content(UserContentClearRequest(1))

    assert raised.value.clear_error is None
    assert str(raised.value.recovery_error) == "restart failed"
    assert events == ["executor-stop", "plugin:good", "executor-start-paused"]
    assert checkpoint.applied_generation == 0
    assert executor.state.value == "stopped"


@pytest.mark.asyncio
async def test_checkpoint_failure_requiesces_executor_and_stays_pending() -> None:
    events: list[str] = []
    plugin = _RecordingPlugin("good", events)
    checkpoint = _Checkpoint(fail_mark=True)
    executor = _Executor(events)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(
            plugins=(("good", plugin, {}),),
            sensors=(),
        ),
        current_generation=1,
        checkpoint=checkpoint,
        executor=executor,
    )

    with pytest.raises(PluginUserContentClearRecoveryError) as raised:
        async with coordinator.user_content_clear_boundary() as session:
            await session.clear_user_content(UserContentClearRequest(1))

    assert str(raised.value.recovery_error) == "checkpoint failed"
    assert raised.value.quiesce_error is None
    assert events == [
        "executor-stop",
        "plugin:good",
        "executor-start-paused",
        "executor-stop",
    ]
    assert checkpoint.applied_generation == 0
    assert executor.state.value == "stopped"


@pytest.mark.asyncio
async def test_resume_failure_rolls_checkpoint_back_and_stays_stopped() -> None:
    events: list[str] = []
    plugin = _RecordingPlugin("good", events)
    checkpoint = _Checkpoint()
    executor = _Executor(events, fail_resume=True)
    coordinator = _coordinator(
        snapshot=PluginUserContentTargetSnapshot(
            plugins=(("good", plugin, {}),),
            sensors=(),
        ),
        current_generation=1,
        checkpoint=checkpoint,
        executor=executor,
    )

    with pytest.raises(PluginUserContentClearRecoveryError) as raised:
        async with coordinator.user_content_clear_boundary() as session:
            await session.clear_user_content(UserContentClearRequest(1))

    assert str(raised.value.recovery_error) == "resume failed"
    assert checkpoint.applied_generation == 0
    assert executor.state.value == "stopped"
    assert events == [
        "executor-stop",
        "plugin:good",
        "executor-start-paused",
        "executor-resume",
        "executor-stop",
    ]
