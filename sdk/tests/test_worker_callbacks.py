"""Worker callback completion must never swallow subscription cancellation."""

import asyncio
from concurrent.futures import Future
from io import BytesIO

import pytest
from magi_plugin_sdk.runtime import SourceChange
from magi_plugin_sdk.transport import pack, write_frame
from magi_plugin_sdk.worker import (
    RemoteChannelPort,
    RemoteSourceEmitter,
    WorkerHost,
    WorkerProgress,
    WorkerServer,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["source", "channel", "capability", "progress", "host_service"])
async def test_callback_completion_preserves_concurrent_cancellation(kind):
    server = WorkerServer(BytesIO(), BytesIO())
    emitter = RemoteSourceEmitter(server, "source:test")
    calls = {
        "source": lambda: emitter.emit(SourceChange(object_id="event", version="1", payload={})),
        "channel": lambda: RemoteChannelPort(server, "session_mapper").resolve_or_create(),
        "capability": lambda: WorkerHost(server).call("fixture", "fixture"),
        "progress": lambda: WorkerProgress(server)({}),
        "host_service": lambda: server._host_service_callback("fixture", {}),
    }
    task = asyncio.create_task(calls[kind]())
    try:
        await asyncio.sleep(0)
        callback = next(iter(server.callbacks.values()))
        callback.set_result(None)
        # Let wrap_future copy the completed result, then cancel before its
        # waiter resumes. Both outcomes are ready in the same event-loop turn.
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not server.callbacks
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_callback_deadline_releases_its_pending_registration():
    server = WorkerServer(BytesIO(), BytesIO())
    server.callback_timeout = 0
    with pytest.raises(asyncio.TimeoutError):
        await WorkerHost(server).call("fixture", "fixture")
    await asyncio.sleep(0)
    assert not server.callbacks


@pytest.mark.parametrize("ok", [True, False])
def test_reply_reader_survives_callback_cancellation_after_its_done_check(ok):
    class CancelBeforeCompletion(Future):
        def set_result(self, result):
            self.cancel()
            super().set_result(result)

        def set_exception(self, exception):
            self.cancel()
            super().set_exception(exception)

    reader = BytesIO()
    for identifier in ("cancelled", "next"):
        write_frame(reader, pack({
            "kind": "callback_result", "id": identifier,
            "ok": ok if identifier == "cancelled" else True, "result": 42,
        }))
    reader.seek(0)
    server = WorkerServer(reader, BytesIO())
    cancelled, following = CancelBeforeCompletion(), Future()
    server.callbacks.update(cancelled=cancelled, next=following)
    server._reader()
    assert cancelled.cancelled()
    assert following.result(timeout=0) == 42
