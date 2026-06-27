from __future__ import annotations

import pytest

from types import SimpleNamespace

from magi.bootstrap.worker_app import _begin_runtime_drain, _publish_runtime_heartbeat


class _FakeRuntimeTraceStore:
    def __init__(self) -> None:
        self.records: list[object] = []

    async def upsert_runtime_heartbeat(self, record) -> None:  # type: ignore[no-untyped-def]
        self.records.append(record)


class _FakeRuntimeCommandQueue:
    async def get_stats(self) -> dict[str, int]:
        return {"pending_count": 7}


@pytest.mark.asyncio
async def test_publish_runtime_heartbeat_writes_store_record(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _FakeRuntimeTraceStore()

    monkeypatch.setattr("magi.bootstrap.worker_app.resolve_runtime_trace_store", lambda: store)
    monkeypatch.setattr(
        "magi.bootstrap.worker_app.require_runtime_command_queue",
        lambda: _FakeRuntimeCommandQueue(),
    )

    await _publish_runtime_heartbeat(
        instance_id="runtime-1",
        started_at_ms=100,
        status="ready",
    )

    assert len(store.records) == 1
    record = store.records[0]
    assert record.role == "ipc_worker"
    assert record.instance_id == "runtime-1"
    assert record.status == "ready"
    assert record.queue_backlog == 7


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
