from __future__ import annotations

import asyncio
from pathlib import Path
import threading

import pytest

from magi.plugins.operation_execution import (
    MAX_CONCURRENT_PLUGIN_PREPARATIONS,
    run_plugin_archive_operation,
    run_plugin_preparation_operation,
)
from magi.plugins.discovery import MAX_PLUGIN_MANIFEST_BYTES, load_plugin_manifest


@pytest.mark.asyncio
async def test_archive_operations_use_one_dedicated_worker() -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    active_operations = 0
    max_active_operations = 0
    state_lock = threading.Lock()

    def operation(started: threading.Event, *, wait: bool) -> str:
        nonlocal active_operations, max_active_operations
        with state_lock:
            active_operations += 1
            max_active_operations = max(max_active_operations, active_operations)
        started.set()
        if wait:
            assert release_first.wait(timeout=2)
        with state_lock:
            active_operations -= 1
        return threading.current_thread().name

    first_task = asyncio.create_task(
        run_plugin_archive_operation(lambda: operation(first_started, wait=True))
    )
    assert await asyncio.to_thread(first_started.wait, 1)
    second_task = asyncio.create_task(
        run_plugin_archive_operation(lambda: operation(second_started, wait=False))
    )
    await asyncio.sleep(0.05)

    assert not second_started.is_set()
    release_first.set()
    first_thread, second_thread = await asyncio.gather(first_task, second_task)
    assert max_active_operations == 1
    assert first_thread.startswith("magi-plugin-archive")
    assert second_thread.startswith("magi-plugin-archive")


@pytest.mark.asyncio
async def test_plugin_preparation_is_bounded_without_blocking_event_loop() -> None:
    release = threading.Event()
    state_lock = threading.Lock()
    active = 0
    max_active = 0
    started = 0

    def prepare() -> str:
        nonlocal active, max_active, started
        with state_lock:
            active += 1
            started += 1
            max_active = max(max_active, active)
        if not release.wait(timeout=3):
            raise TimeoutError("Timed out waiting to release plugin preparation")
        with state_lock:
            active -= 1
        return threading.current_thread().name

    tasks = [
        asyncio.create_task(run_plugin_preparation_operation(prepare))
        for _ in range(MAX_CONCURRENT_PLUGIN_PREPARATIONS + 3)
    ]
    deadline = asyncio.get_running_loop().time() + 1
    while started < MAX_CONCURRENT_PLUGIN_PREPARATIONS:
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.01)

    heartbeat_started = asyncio.get_running_loop().time()
    await asyncio.sleep(0.02)
    heartbeat_elapsed = asyncio.get_running_loop().time() - heartbeat_started

    with state_lock:
        assert started == MAX_CONCURRENT_PLUGIN_PREPARATIONS
        assert max_active == MAX_CONCURRENT_PLUGIN_PREPARATIONS
    assert heartbeat_elapsed < 0.2

    release.set()
    thread_names = await asyncio.gather(*tasks)
    assert all(name.startswith("magi-plugin-prepare") for name in thread_names)
    assert max_active == MAX_CONCURRENT_PLUGIN_PREPARATIONS


def test_plugin_manifest_has_a_dedicated_size_limit(tmp_path: Path) -> None:
    manifest_path = tmp_path / "plugin.toml"
    manifest_path.write_bytes(b"#" * (MAX_PLUGIN_MANIFEST_BYTES + 1))

    with pytest.raises(ValueError, match="manifest exceeds"):
        load_plugin_manifest(manifest_path, source="external")
