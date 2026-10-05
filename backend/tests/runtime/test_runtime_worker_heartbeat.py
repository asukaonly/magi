from __future__ import annotations

import pytest

from types import SimpleNamespace

from magi.bootstrap.worker_app import _begin_runtime_drain


@pytest.mark.asyncio
async def test_begin_runtime_drain_marks_processor_before_waiting_for_idle(monkeypatch):
    import asyncio

    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    class Processor:
        def begin_draining(self):
            calls.append("drain")

        async def wait_until_idle(self, timeout_seconds=None):
            calls.append(("wait", timeout_seconds))
            entered.set()
            await release.wait()
            calls.append("idle")

    context = SimpleNamespace(
        runtime_commands=SimpleNamespace(runtime_command_processor=Processor())
    )
    monkeypatch.setattr(
        "magi.bootstrap.worker_app.get_container",
        lambda: SimpleNamespace(runtime_bootstrap_context=lambda: context),
    )
    task = asyncio.create_task(_begin_runtime_drain(timeout_seconds=3.0))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert calls == ["drain", ("wait", 3.0)]
        assert not task.done()
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=2)
    assert calls == ["drain", ("wait", 3.0), "idle"]
