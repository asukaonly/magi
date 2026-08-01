from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.plugins.lifecycle import PluginSystemModule


def _patch_plugin_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def build_plugin_runtime(
        *,
        tool_registry: object,
        request_sensor_schedule_refresh: Callable[[], None],
        activate_enabled: bool,
    ) -> SimpleNamespace:
        del tool_registry
        captured["request_sensor_schedule_refresh"] = request_sensor_schedule_refresh
        captured["activate_enabled"] = activate_enabled
        return SimpleNamespace(
            plugin_manager=object(),
            plugin_projection_service=object(),
            sensor_registry=object(),
        )

    monkeypatch.setattr(
        "magi.plugins.lifecycle.build_plugin_runtime",
        build_plugin_runtime,
    )

    class _ClearCoordinator:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            captured["clear_coordinator_kwargs"] = kwargs

        async def has_pending_generation(self) -> bool:
            captured["clear_checked"] = True
            failure = captured.get("clear_check_failure")
            if failure is not None:
                raise failure
            return bool(captured.get("clear_pending", False))

    monkeypatch.setattr(
        "magi.plugins.lifecycle.PluginUserContentClearCoordinator",
        _ClearCoordinator,
    )
    return captured


def _runtime_context() -> RuntimeBootstrapContext:
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = SimpleNamespace(
        message_queue_db_path="/tmp/plugin-lifecycle-message-queue.db"
    )

    async def read_current_clear_generation() -> int:
        return 0

    async def read_full_user_content_clear_state() -> SimpleNamespace:
        return SimpleNamespace(
            status="idle",
            transaction_id=None,
        )

    context.runtime_commands.runtime_command_queue = SimpleNamespace(
        read_current_clear_generation=read_current_clear_generation,
        read_full_user_content_clear_state=read_full_user_content_clear_state,
    )
    return context


@pytest.mark.asyncio
async def test_sensor_schedule_refresh_from_worker_runs_on_runtime_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_plugin_runtime(monkeypatch)
    context = _runtime_context()
    runtime_thread_id = threading.get_ident()
    refresh_called = asyncio.Event()
    refresh_thread_ids: list[int] = []

    def refresh_sensor_schedule() -> None:
        asyncio.get_running_loop()
        refresh_thread_ids.append(threading.get_ident())
        refresh_called.set()

    module = PluginSystemModule(
        context,
        tool_registry=object(),
        request_sensor_schedule_refresh=refresh_sensor_schedule,
    )
    await module.init()

    assert "clear_checked" in captured
    assert captured["activate_enabled"] is True
    assert context.plugins.user_content_clear_coordinator is not None

    worker_errors: list[BaseException] = []

    def request_from_worker() -> None:
        try:
            captured["request_sensor_schedule_refresh"]()
        except BaseException as exc:  # pragma: no cover - asserted below
            worker_errors.append(exc)

    worker = threading.Thread(target=request_from_worker)
    worker.start()
    await asyncio.to_thread(worker.join)
    await asyncio.wait_for(refresh_called.wait(), timeout=1)

    assert worker_errors == []
    assert refresh_thread_ids == [runtime_thread_id]


@pytest.mark.asyncio
async def test_sensor_schedule_refresh_is_ignored_after_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_plugin_runtime(monkeypatch)
    context = _runtime_context()
    refresh_thread_ids: list[int] = []
    module = PluginSystemModule(
        context,
        tool_registry=object(),
        request_sensor_schedule_refresh=lambda: refresh_thread_ids.append(threading.get_ident()),
    )
    await module.init()
    await module.shutdown()

    await asyncio.to_thread(captured["request_sensor_schedule_refresh"])
    await asyncio.sleep(0)

    assert refresh_thread_ids == []


def test_sensor_schedule_refresh_is_ignored_after_runtime_loop_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_plugin_runtime(monkeypatch)
    context = _runtime_context()
    refresh_thread_ids: list[int] = []
    module = PluginSystemModule(
        context,
        tool_registry=object(),
        request_sensor_schedule_refresh=lambda: refresh_thread_ids.append(threading.get_ident()),
    )
    runtime_loop = asyncio.new_event_loop()
    runtime_loop.run_until_complete(module.init())
    runtime_loop.close()

    worker_errors: list[BaseException] = []

    def request_from_worker() -> None:
        try:
            captured["request_sensor_schedule_refresh"]()
        except BaseException as exc:  # pragma: no cover - asserted below
            worker_errors.append(exc)

    worker = threading.Thread(target=request_from_worker)
    worker.start()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert worker_errors == []
    assert refresh_thread_ids == []


@pytest.mark.asyncio
async def test_pending_plugin_clear_without_a_transaction_blocks_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_plugin_runtime(monkeypatch)
    captured["clear_pending"] = True
    context = _runtime_context()
    module = PluginSystemModule(
        context,
        tool_registry=object(),
        request_sensor_schedule_refresh=lambda: None,
    )

    with pytest.raises(RuntimeError, match="no durable recovery owner"):
        await module.init()

    assert captured["clear_checked"] is True
    assert context.agent_runtime.sensor_sync_executor is None


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_checkpoint_pending", [False, True])
async def test_pending_desktop_transaction_allows_runtime_to_start_for_recovery(
    monkeypatch: pytest.MonkeyPatch,
    plugin_checkpoint_pending: bool,
) -> None:
    captured = _patch_plugin_runtime(monkeypatch)
    captured["clear_pending"] = plugin_checkpoint_pending
    context = _runtime_context()

    async def read_pending_state() -> SimpleNamespace:
        return SimpleNamespace(
            status="pending",
            transaction_id="clear-recovery-transaction",
        )

    context.runtime_commands.runtime_command_queue.read_full_user_content_clear_state = (
        read_pending_state
    )
    module = PluginSystemModule(
        context,
        tool_registry=object(),
        request_sensor_schedule_refresh=lambda: None,
    )

    await module.init()

    assert captured["clear_checked"] is True
    assert context.plugins.user_content_clear_coordinator is not None
    assert captured["activate_enabled"] is False
    assert context.runtime_commands.full_clear_recovery_pending is True
