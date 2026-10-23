"""A live read cannot bypass source-identity tombstones or clear generations."""
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.clear_generation import advance_memory_clear_generation
from magi.memory.source_event_governance import business_source_references, tombstone_source_event_ids
from magi.memory.source_read_governance import SourceReadGovernance


@asynccontextmanager
async def guard():
    yield


@pytest.mark.asyncio
async def test_live_object_identity_obeys_durable_forgetting(runtime_paths_with_schema):
    path = runtime_paths_with_schema.memory_db_path
    memory = SimpleNamespace(memory_db_path=path, memory_operation_guard=guard, memory_operation_epoch=lambda: 0)
    governance = SourceReadGovernance(memory)
    boundary = await governance.capture()
    args = dict(source_type="mail", source_item_id="source:stable-account-object", occurred_at=100, event_ids=[])
    assert await governance.visible(boundary, **args)
    async with sqlite_connection_async(path) as db:
        await tombstone_source_event_ids(db, event_ids=business_source_references(
            source="mail", event_type="SOURCE_EVENT", source_item_id=args["source_item_id"]),
            reason="user_forget", created_at=200)
        await db.commit()
    assert not await governance.visible(boundary, **args)
    assert await governance.visible(boundary, **{**args, "source_item_id": "source:another-account-object"})


@pytest.mark.asyncio
async def test_clear_during_query_and_pre_clear_content_are_blocked(runtime_paths_with_schema):
    path = runtime_paths_with_schema.memory_db_path
    memory = SimpleNamespace(memory_db_path=path, memory_operation_guard=guard, memory_operation_epoch=lambda: 0)
    governance = SourceReadGovernance(memory)
    old = await governance.capture()
    async with sqlite_connection_async(path) as db:
        await advance_memory_clear_generation(db, updated_at=200)
        await db.commit()
    assert not await governance.unchanged(old)
    fresh = await governance.capture()
    for occurred_at in (None, 100):
        assert not await governance.visible(fresh, source_type="mail", source_item_id="new", occurred_at=occurred_at, event_ids=[])
    assert await governance.visible(fresh, source_type="mail", source_item_id="new", occurred_at=300, event_ids=[])


@pytest.mark.asyncio
async def test_time_range_and_correction_lineage_apply_to_live_versions(runtime_paths_with_schema):
    from unittest.mock import AsyncMock
    path = runtime_paths_with_schema.memory_db_path
    l2 = SimpleNamespace(db_path=str(path), active_correction_evidence_event_ids=AsyncMock(return_value=set()))
    memory = SimpleNamespace(memory_db_path=path, l2=l2, memory_operation_guard=guard, memory_operation_epoch=lambda: 0)
    governance = SourceReadGovernance(memory)
    boundary = await governance.capture()
    args = dict(source_type="mail", source_item_id="object", occurred_at=100, event_ids=["old-version"])
    assert await governance.visible(boundary, **args)
    l2.active_correction_evidence_event_ids.return_value = {"old-version"}
    assert not await governance.visible(boundary, **args)
    l2.active_correction_evidence_event_ids.return_value = set()
    async with sqlite_connection_async(path) as db:
        await db.execute("""INSERT INTO memory_forget_operations
            (operation_id, selector_kind, selector_hash, selector_json, reason, status, phase, created_at, updated_at)
            VALUES ('range', 'time_range', 'hash', '{}', 'user_forget', 'completed', 'completed', 200, 200)""")
        await db.execute("""INSERT INTO memory_time_range_forget_barriers
            (operation_id, target_id, selector_hash, range_start, range_end, delete_l1_events, reason, created_at)
            VALUES ('range', 'time:range', 'hash', 90, 110, 1, 'user_forget', 200)""")
        await db.commit()
    assert not await governance.unchanged(boundary)
    boundary = await governance.capture()
    assert not await governance.visible(boundary, **args)
    assert not await governance.visible(boundary, **{**args, "occurred_at": None})
    assert await governance.visible(boundary, **{**args, "occurred_at": 120})
