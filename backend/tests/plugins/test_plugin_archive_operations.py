from __future__ import annotations

import asyncio
from pathlib import Path
import threading

import pytest

from magi.plugins.archive_operations import run_plugin_archive_operation
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


def test_plugin_manifest_has_a_dedicated_size_limit(tmp_path: Path) -> None:
    manifest_path = tmp_path / "plugin.toml"
    manifest_path.write_bytes(b"#" * (MAX_PLUGIN_MANIFEST_BYTES + 1))

    with pytest.raises(ValueError, match="manifest exceeds"):
        load_plugin_manifest(manifest_path, source="external")
