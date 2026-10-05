from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from magi.memory.event_contracts import IngestTarget
from magi.memory.layer_protocol import FanOutContext, WILDCARD_EVENT_TYPES
from magi.memory.layers.l2_layer import L2ProjectionLayer

from ._helpers import make_event


@pytest.mark.parametrize(
    ("has_store", "eligible", "target", "stored_id", "accepted"),
    [
        (True, True, IngestTarget.L1_ONLY, "stored", True),
        (False, True, IngestTarget.L1_ONLY, "stored", False),
        (True, False, IngestTarget.L1_ONLY, "stored", False),
        (True, True, IngestTarget.RUNTIME_ONLY, "stored", False),
        (True, True, IngestTarget.L1_ONLY, None, False),
    ],
)
def test_l2_projection_admission_requires_store_eligible_l1_event_and_identity(
    has_store, eligible, target, stored_id, accepted
):
    layer = L2ProjectionLayer(AsyncMock() if has_store else None)
    assert (
        layer.accepts(
            make_event(cognition_eligible=eligible, ingest_target=target),
            FanOutContext(markers={"stored_event_id": stored_id}),
        )
        is accepted
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner", "maximum", "minimum", "wait"),
    [("owner-a", "5", None, "1.5"), ("bootstrap:user-x", 1, 1, 0.5)],
)
async def test_l2_projection_dispatch_preserves_explicit_batching_contract(
    owner, maximum, minimum, wait
):
    store = AsyncMock()
    store.enqueue_projection_job.return_value = True
    layer = L2ProjectionLayer(store)
    assert layer.accepts_event_types == WILDCARD_EVENT_TYPES
    assert layer.requires_write_lock is True
    event = make_event(
        metadata={
            "l2_batch_owner": owner,
            "l2_batch_max_events": maximum,
            "l2_batch_min_ready_events": minimum,
            "l2_batch_max_wait_seconds": wait,
        }
    )
    result = await layer.ingest(event, FanOutContext(markers={"stored_event_id": "stored-id"}))
    store.enqueue_projection_job.assert_awaited_once_with(
        event_id="stored-id",
        source="chat",
        event_type="USER_MESSAGE",
        batch_owner=owner,
        catch_up_owner=None,
        max_events=int(maximum),
        min_ready_events=minimum,
        max_wait_seconds=float(wait),
    )
    assert result.layer_name == "l2"
    assert result.ok is True
    assert result.markers == {"l2_job_enqueued": True, "l2_evidence_class": "user_self_report"}


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
