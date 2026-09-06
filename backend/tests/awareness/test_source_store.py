"""Atomic source acceptance, version ownership, and revocable host resources."""

from __future__ import annotations

import asyncio

import pytest
from magi_plugin_sdk.runtime import InvocationIdentity, PluginConnection, SourceChange, SourceChangeBatch

from magi.awareness.source_store import SourceCheckpointConflict, SourceStore
from magi.plugins.operation_execution import plugin_runtime_operation, plugin_user_content_clear_boundary


def connection(name="account-a"):
    return PluginConnection(connection_id=name, plugin_id="notes", display_name=name, enabled=True)


def change(version="1", **kwargs):
    return SourceChange(object_id="note", version=version, payload={"text": version}, **kwargs)


async def accept(store, owner, changes, cursor):
    checkpoint = await store.checkpoint(owner, "notes.source", "notes")
    pending = await store.stage_batch(owner, checkpoint, SourceChangeBatch(changes=changes, next_cursor=cursor))
    for item in changes:
        if item.operation == "upsert":
            await store.record_receipt(pending, item, event_id="memory:" + item.version, outcome="persisted")
    return await store.accept_batch(owner, pending)


@pytest.mark.asyncio
async def test_same_object_id_isolated_between_connections_and_revision_replay(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    left = await accept(store, connection(), [change()], "a1")
    right = await accept(store, connection("account-b"), [change()], "b1")
    left = await accept(store, connection(), [change("2")], "a2")
    left = await accept(store, connection(), [change()], "a3")
    assert (await store.current_object(left, "note"))["version"] == "2"
    assert (await store.current_object(right, "note"))["version"] == "1"
    assert (await store.checkpoint(connection("account-b"), "notes.source", "notes")).cursor == "b1"


@pytest.mark.asyncio
async def test_unconfirmed_batch_cannot_advance_and_survives_restart(tmp_path):
    path = tmp_path / "sources.db"
    store = SourceStore(path)
    owner = connection()
    checkpoint = await store.checkpoint(owner, "notes.source", "notes")
    batch = SourceChangeBatch(changes=[change(), SourceChange(object_id="two", version="1")], next_cursor="next")
    pending = await store.stage_batch(owner, checkpoint, batch)
    await store.record_receipt(pending, batch.changes[0], event_id="first", outcome="persisted")
    with pytest.raises(RuntimeError, match="unconfirmed"):
        await store.accept_batch(owner, pending)
    reopened = SourceStore(path)
    assert await reopened.current_object(checkpoint, "note") is None
    assert (await reopened.checkpoint(owner, "notes.source", "notes")).cursor is None
    resumed = await reopened.pending(checkpoint)
    assert resumed.batch == batch
    await reopened.record_receipt(resumed, batch.changes[1], event_id="second", outcome="duplicate")
    assert (await reopened.accept_batch(owner, resumed)).cursor == "next"


@pytest.mark.asyncio
async def test_invalid_revision_reuse_rolls_back_entire_batch(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    owner = connection()
    checkpoint = await accept(store, owner, [change()], "one")
    with pytest.raises(ValueError, match="reused"):
        await store.stage_batch(owner, checkpoint, SourceChangeBatch(changes=[
            SourceChange(object_id="new", version="1"),
            SourceChange(object_id="note", version="1", payload={"text": "tampered"}),
        ], next_cursor="two"))
    assert await store.pending(checkpoint) is None
    assert (await store.checkpoint(owner, "notes.source", "notes")).cursor == "one"
    with pytest.raises(SourceCheckpointConflict):
        await store.version(checkpoint, SourceChange(object_id="new", version="1"))


@pytest.mark.asyncio
async def test_resource_ownership_version_and_operation_validation(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    owner = connection()
    ref = await store.register_resource(owner, b"document", media_type="text/plain")
    identity = InvocationIdentity(invocation_id="call", plugin_id="notes", connection_id=owner.connection_id, principal_id="user", trigger="user")
    assert await store.validate_operation_resource(identity, ref) is True
    assert await store.validate_operation_resource(identity, ref.model_copy(update={"size_bytes": 0})) is False
    with pytest.raises(PermissionError):
        await store.read_resource(connection("account-b"), ref)
    checkpoint = await store.checkpoint(connection("account-b"), "notes.source", "notes")
    with pytest.raises(PermissionError):
        await store.stage_batch(connection("account-b"), checkpoint, SourceChangeBatch(changes=[change(resources=[ref])]))
    await store.disconnect_connection(owner.connection_id)
    assert await store.validate_operation_resource(identity, ref) is False
    with pytest.raises(SourceCheckpointConflict):
        await store.read_resource(owner, ref)


@pytest.mark.asyncio
async def test_delete_marks_source_state_and_revokes_object_resources(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    owner = connection()
    ref = await store.register_resource(owner, b"document", media_type="text/plain")
    checkpoint = await accept(store, owner, [change(resources=[ref])], "one")
    version = await store.version(checkpoint, change())
    evidence = version["evidence_ref"]
    checkpoint = await accept(store, owner, [SourceChange(object_id="note", version="2", operation="delete")], "two")
    assert (await store.current_object(checkpoint, "note"))["deleted"] == 1
    with pytest.raises(PermissionError):
        await store.read_resource(owner, ref)
    assert await store.read_resource(owner, evidence) == b'{"text":"1"}'
    assert (await store.version(checkpoint, change()))["receipt"]["event_id"] == "memory:1"


@pytest.mark.asyncio
async def test_clear_erases_payloads_preserves_cursor_and_fences_old_work(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    owner = connection()
    checkpoint = await accept(store, owner, [change()], "one")
    old_evidence = (await store.version(checkpoint, change()))["evidence_ref"]
    pending = await store.stage_batch(owner, checkpoint, SourceChangeBatch(changes=[change("2")], next_cursor="two"))
    async with plugin_user_content_clear_boundary():
        await store.clear_user_content()
    with pytest.raises(SourceCheckpointConflict):
        await store.accept_batch(owner, pending)
    with pytest.raises(SourceCheckpointConflict):
        await store.stage_batch(owner, checkpoint, SourceChangeBatch())
    fresh = await store.checkpoint(owner, "notes.source", "notes")
    assert fresh.cursor == "one"
    assert await store.pending(fresh) is None
    await accept(store, owner, [change()], "three")
    with pytest.raises(PermissionError):
        await store.read_resource(owner, old_evidence)


@pytest.mark.asyncio
async def test_global_clear_waits_for_admitted_source_work(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    started, finish, cleared = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def sync():
        async with plugin_runtime_operation():
            started.set()
            await finish.wait()
            await accept(store, connection(), [change()], "cursor")

    async def clear():
        async with plugin_user_content_clear_boundary():
            await store.clear_user_content()
            cleared.set()

    task = asyncio.create_task(sync())
    await started.wait()
    clear_task = asyncio.create_task(clear())
    await asyncio.sleep(0)
    assert not cleared.is_set()
    finish.set()
    await asyncio.gather(task, clear_task)
    checkpoint = await store.checkpoint(connection(), "notes.source", "notes")
    assert checkpoint.cursor == "cursor"
    assert await store.current_object(checkpoint, "note") is None


@pytest.mark.asyncio
async def test_governed_skip_scrubs_staged_evidence_before_retry(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    owner = connection()
    checkpoint = await store.checkpoint(owner, "notes.source", "notes")
    item = change()
    pending = await store.stage_batch(owner, checkpoint, SourceChangeBatch(changes=[item], next_cursor="one"))
    evidence = (await store.version(checkpoint, item))["evidence_ref"]
    await store.record_receipt(pending, item, event_id="forgotten", outcome="governed_skip")
    assert (await store.pending(checkpoint)).batch.changes[0].payload == {}
    with pytest.raises(PermissionError):
        await store.read_resource(owner, evidence)
    assert (await store.accept_batch(owner, pending)).cursor == "one"


@pytest.mark.asyncio
async def test_cursor_compare_and_swap_rejects_racing_collector(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    owner = connection()
    checkpoint = await store.checkpoint(owner, "notes.source", "notes")
    await accept(store, owner, [change()], "one")
    with pytest.raises(SourceCheckpointConflict):
        await store.stage_batch(owner, checkpoint, SourceChangeBatch(next_cursor="stale"))
    assert (await store.checkpoint(owner, "notes.source", "notes")).cursor == "one"
