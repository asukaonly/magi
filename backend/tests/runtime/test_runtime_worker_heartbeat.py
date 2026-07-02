from __future__ import annotations

import pytest

from types import SimpleNamespace

from magi.bootstrap import worker_app
from magi.bootstrap.worker_app import _begin_runtime_drain


def test_worker_app_no_longer_exports_persisted_heartbeat_writer() -> None:
    assert not hasattr(worker_app, "_publish_runtime_heartbeat")


@pytest.mark.asyncio
async def test_begin_runtime_drain_marks_processor_and_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeProcessor:
        def __init__(self) -> None:
            self.drain_started = False
            self.wait_timeout: float | None = None

        def begin_draining(self) -> None:
            self.drain_started = True

        async def wait_until_idle(self, timeout_seconds: float | None = None) -> None:
            self.wait_timeout = timeout_seconds

    processor = _FakeProcessor()
    context = SimpleNamespace(runtime_commands=SimpleNamespace(runtime_command_processor=processor))
    container = SimpleNamespace(runtime_bootstrap_context=lambda: context)

    monkeypatch.setattr("magi.bootstrap.worker_app.get_container", lambda: container)

    await _begin_runtime_drain(timeout_seconds=3.0)

    assert processor.drain_started is True
    assert processor.wait_timeout == 3.0
