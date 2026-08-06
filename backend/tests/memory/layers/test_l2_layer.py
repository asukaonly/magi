from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from magi.memory.event_contracts import IngestTarget
from magi.memory.layer_protocol import FanOutContext, WILDCARD_EVENT_TYPES
from magi.memory.layers.l2_layer import L2ProjectionLayer

from ._helpers import make_event


def test_l2_projection_basics():
    layer = L2ProjectionLayer(AsyncMock())
    assert layer.accepts_event_types == WILDCARD_EVENT_TYPES
    assert layer.requires_write_lock is True
    assert layer.layer_name == "l2"


def test_l2_projection_rejects_when_not_cognition_eligible():
    layer = L2ProjectionLayer(AsyncMock())
    ctx = FanOutContext(markers={"stored_event_id": "x"})
    assert not layer.accepts(make_event(cognition_eligible=False), ctx)


def test_l2_projection_requires_stored_event_id_and_l1_target():
    layer = L2ProjectionLayer(AsyncMock())
    event = make_event(ingest_target=IngestTarget.L1_ONLY)
    assert not layer.accepts(event, FanOutContext())
    assert layer.accepts(event, FanOutContext(markers={"stored_event_id": "x"}))
    not_l1 = make_event(ingest_target=IngestTarget.RUNTIME_ONLY)
    assert not layer.accepts(not_l1, FanOutContext(markers={"stored_event_id": "x"}))


def test_l2_projection_rejects_without_store():
    assert not L2ProjectionLayer(None).accepts(
        make_event(), FanOutContext(markers={"stored_event_id": "x"})
    )


@pytest.mark.asyncio
async def test_l2_projection_enqueues_with_metadata_coercion():
    store = AsyncMock()
    store.enqueue_projection_job.return_value = True
    layer = L2ProjectionLayer(store)
    event = make_event(metadata={
        "l2_batch_owner": "owner-a",
        "l2_batch_max_events": 5,
        "l2_batch_max_wait_seconds": 1.5,
    })
    ctx = FanOutContext(markers={"stored_event_id": "stored-id"})
    result = await layer.ingest(event, ctx)
    kwargs = store.enqueue_projection_job.await_args.kwargs
    assert kwargs["event_id"] == "stored-id"
    assert kwargs["batch_owner"] == "owner-a"
    assert kwargs["max_events"] == 5
    assert kwargs["max_wait_seconds"] == 1.5
    assert kwargs["catch_up_owner"] is None
    assert result.markers == {
        "l2_job_enqueued": True,
        "l2_evidence_class": "user_self_report",
    }


@pytest.mark.asyncio
async def test_l2_projection_skips_assistant_freeform_by_policy():
    store = AsyncMock()
    layer = L2ProjectionLayer(store)
    event = make_event(
        event_type="AI_RESPONSE",
        source="assistant",
        author_type="assistant",
    )
    ctx = FanOutContext(markers={"stored_event_id": "stored-id"})

    result = await layer.ingest(event, ctx)

    store.enqueue_projection_job.assert_not_awaited()
    assert result.ok is True
    assert result.markers == {
        "l2_job_enqueued": False,
        "l2_job_skipped_by_policy": True,
        "l2_evidence_class": "assistant_freeform",
        "l2_skip_reason": "assistant_freeform",
    }


@pytest.mark.asyncio
async def test_l2_projection_defaults_batching_metadata_for_chat_messages():
    """Chat-style events without explicit l2_batch_* metadata should still be enqueued
    with a session-derived batch_owner and sane defaults so they participate in
    owner-aware batching instead of falling into the NULL-owner fast path."""
    store = AsyncMock()
    store.enqueue_projection_job.return_value = True
    layer = L2ProjectionLayer(store)
    event = make_event(metadata=None)
    ctx = FanOutContext(markers={"stored_event_id": "stored-id"})
    await layer.ingest(event, ctx)
    kwargs = store.enqueue_projection_job.await_args.kwargs
    assert kwargs["event_id"] == "stored-id"
    assert kwargs["batch_owner"] == "chat:sess"
    assert kwargs["max_events"] is not None and kwargs["max_events"] > 1
    assert kwargs["max_wait_seconds"] is not None and kwargs["max_wait_seconds"] > 0


@pytest.mark.asyncio
async def test_l2_projection_explicit_metadata_overrides_defaults():
    """When metadata explicitly sets batching keys, defaults must not clobber them."""
    store = AsyncMock()
    store.enqueue_projection_job.return_value = True
    layer = L2ProjectionLayer(store)
    event = make_event(metadata={
        "l2_batch_owner": "bootstrap:user-x",
        "l2_batch_max_events": 1,
        "l2_batch_min_ready_events": 1,
        "l2_batch_max_wait_seconds": 0.5,
    })
    ctx = FanOutContext(markers={"stored_event_id": "stored-id"})
    await layer.ingest(event, ctx)
    kwargs = store.enqueue_projection_job.await_args.kwargs
    assert kwargs["batch_owner"] == "bootstrap:user-x"
    assert kwargs["max_events"] == 1
    assert kwargs["min_ready_events"] == 1
    assert kwargs["max_wait_seconds"] == 0.5


@pytest.mark.asyncio
async def test_l2_projection_no_session_leaves_batching_unconstrained():
    """Without a session_id and without explicit metadata, the layer should not
    invent a batch_owner — that's the legitimate NULL-owner fallback path."""
    store = AsyncMock()
    store.enqueue_projection_job.return_value = True
    layer = L2ProjectionLayer(store)

    from magi.memory.event_contracts import (
        IngestTarget,
        MemoryDomain,
        MemoryEvent,
        RetentionClass,
        TomDepth,
    )
    event = MemoryEvent(
        event_id="evt_1",
        correlation_id="cor_1",
        timestamp=1.0,
        created_at=1.0,
        event_type="USER_MESSAGE",
        source="chat",
        source_item_id=None,
        memory_domain=MemoryDomain.INTERACTION,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.DISPOSABLE,
        session_id=None,
        turn_id=None,
        user_id=None,
        task_id=None,
        content="hi",
        author_type="user",
        content_type="text",
        importance_score=0.5,
        level=20,
        idempotency_key="idem-1",
        metadata_json=None,
    )
    ctx = FanOutContext(markers={"stored_event_id": "stored-id"})
    await layer.ingest(event, ctx)
    kwargs = store.enqueue_projection_job.await_args.kwargs
    assert kwargs["batch_owner"] is None
