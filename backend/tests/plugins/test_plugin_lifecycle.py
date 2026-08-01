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
    ) -> SimpleNamespace:
        del tool_registry
        captured["request_sensor_schedule_refresh"] = request_sensor_schedule_refresh
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

        async def require_no_pending_generation(self) -> None:
            captured["clear_checked"] = True
            failure = captured.get("clear_check_failure")
            if failure is not None:
                raise failure

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

    context.runtime_commands.runtime_command_queue = SimpleNamespace(
        read_current_clear_generation=read_current_clear_generation
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
async def test_pending_full_clear_blocks_later_runtime_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_plugin_runtime(monkeypatch)
    captured["clear_check_failure"] = RuntimeError("full clear remains pending")
    context = _runtime_context()
    module = PluginSystemModule(
        context,
        tool_registry=object(),
        request_sensor_schedule_refresh=lambda: None,
    )

    with pytest.raises(RuntimeError, match="full clear remains pending"):
        await module.init()

    assert captured["clear_checked"] is True
    assert context.agent_runtime.sensor_sync_executor is None
