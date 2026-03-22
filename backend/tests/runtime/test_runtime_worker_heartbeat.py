from __future__ import annotations

import pytest

from magi.backend_runtime_worker import _publish_runtime_heartbeat


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

    monkeypatch.setattr("magi.backend_runtime_worker.require_runtime_trace_store", lambda: store)
    monkeypatch.setattr(
        "magi.backend_runtime_worker.require_runtime_command_queue",
        lambda: _FakeRuntimeCommandQueue(),
    )

    await _publish_runtime_heartbeat(
        instance_id="runtime-1",
        started_at_ms=100,
        status="ready",
    )

    assert len(store.records) == 1
    record = store.records[0]
    assert record.role == "runtime_worker"
    assert record.instance_id == "runtime-1"
    assert record.status == "ready"
    assert record.queue_backlog == 7
