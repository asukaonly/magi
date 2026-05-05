from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from magi.memory.event_contracts import IngestTarget
from magi.memory.layer_protocol import FanOutContext, WILDCARD_EVENT_TYPES
from magi.memory.layers.l2_layer import L2PipelineLayer, L2ProjectionLayer

from ._helpers import make_event


def test_l2_projection_basics():
    layer = L2ProjectionLayer(AsyncMock())
    assert layer.accepts_event_types == WILDCARD_EVENT_TYPES
    assert layer.requires_write_lock is True
    assert layer.layer_name == "l2"


def test_l2_pipeline_basics():
    layer = L2PipelineLayer(AsyncMock(), AsyncMock())
    assert layer.accepts_event_types == WILDCARD_EVENT_TYPES
    assert layer.requires_write_lock is False
    assert layer.layer_name == "l2_pipeline"


def test_l2_projection_rejects_when_not_cognition_eligible():
    layer = L2ProjectionLayer(AsyncMock())
    ctx = FanOutContext(markers={"stored_event_id": "x"})
    assert not layer.accepts(make_event(cognition_eligible=False), ctx)


def test_l2_projection_requires_stored_event_id_and_l1_target():
    layer = L2ProjectionLayer(AsyncMock())
    event = make_event(ingest_target=IngestTarget.L0_AND_L1)
    assert not layer.accepts(event, FanOutContext())
    assert layer.accepts(event, FanOutContext(markers={"stored_event_id": "x"}))
    not_l1 = make_event(ingest_target=IngestTarget.L0_ONLY)
    assert not layer.accepts(not_l1, FanOutContext(markers={"stored_event_id": "x"}))


def test_l2_projection_rejects_without_store():
    assert not L2ProjectionLayer(None).accepts(
        make_event(), FanOutContext(markers={"stored_event_id": "x"})
    )


def test_l2_pipeline_accepts_when_no_l1_target():
    pipeline = AsyncMock()
    layer = L2PipelineLayer(AsyncMock(), pipeline)
    event = make_event(ingest_target=IngestTarget.L0_ONLY)
    assert layer.accepts(event, FanOutContext())


def test_l2_pipeline_accepts_when_no_store_but_l1_target():
    pipeline = AsyncMock()
    layer = L2PipelineLayer(None, pipeline)
    event = make_event(ingest_target=IngestTarget.L0_AND_L1)
    assert layer.accepts(event, FanOutContext())


def test_l2_pipeline_rejects_when_l1_target_and_store_present():
    layer = L2PipelineLayer(AsyncMock(), AsyncMock())
    event = make_event(ingest_target=IngestTarget.L0_AND_L1)
    assert not layer.accepts(event, FanOutContext())


def test_l2_pipeline_rejects_when_no_pipeline():
    layer = L2PipelineLayer(None, None)
    assert not layer.accepts(make_event(ingest_target=IngestTarget.L0_ONLY), FanOutContext())


def test_l2_pipeline_rejects_when_not_cognition_eligible():
    layer = L2PipelineLayer(None, AsyncMock())
    event = make_event(ingest_target=IngestTarget.L0_ONLY, cognition_eligible=False)
    assert not layer.accepts(event, FanOutContext())


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
    assert result.markers == {"l2_job_enqueued": True}


@pytest.mark.asyncio
async def test_l2_pipeline_enqueues_with_event_id_rewrite():
    pipeline = AsyncMock()
    layer = L2PipelineLayer(None, pipeline)
    event = make_event(event_id="orig", ingest_target=IngestTarget.L0_AND_L1)
    ctx = FanOutContext(markers={"stored_event_id": "rewritten"})
    result = await layer.ingest(event, ctx)
    assert event.event_id == "rewritten"
    pipeline.enqueue_event.assert_awaited_once_with(event)
    assert result.markers["l2_pipeline_enqueued"] is True
