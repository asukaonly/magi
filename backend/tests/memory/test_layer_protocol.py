from __future__ import annotations
import pytest
from magi.memory.layer_protocol import (
    FanOutContext,
    LayerIngestResult,
    MemoryLayer,
)
from magi.memory.store_ingestion import MemoryIngestionMixin
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)


def test_fanout_context_default_markers_empty():
    ctx = FanOutContext()
    assert ctx.markers == {}


def test_layer_ingest_result_defaults():
    r = LayerIngestResult(layer_name="x", ok=True)
    assert r.markers == {}
    assert r.summary == {}
    assert r.layer_name == "x"
    assert r.ok is True


def test_protocol_runtime_checkable():
    class Dummy:
        layer_name = "x"
        accepts_event_types = frozenset({"a"})
        requires_write_lock = False
        required_for_acceptance = False

        def accepts(self, e, c):
            return True

        async def ingest(self, e, c):
            return LayerIngestResult(layer_name="x", ok=True)

    assert isinstance(Dummy(), MemoryLayer)


def test_non_conforming_class_rejected():
    class Bad:
        # missing required attrs
        pass

    assert not isinstance(Bad(), MemoryLayer)


def _memory_event() -> MemoryEvent:
    return MemoryEvent(
        event_id="event-1",
        correlation_id="event-1",
        timestamp=1.0,
        created_at=1.0,
        event_type="TEST_EVENT",
        source="test",
        source_item_id=None,
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=False,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.PERMANENT,
        session_id=None,
        turn_id=None,
        user_id=None,
        task_id=None,
        content="test",
        author_type="system",
        content_type="observation",
        importance_score=0.5,
        level=1,
    )


@pytest.mark.asyncio
async def test_required_layer_failure_propagates() -> None:
    class RequiredLayer:
        layer_name = "required"
        accepts_event_types = frozenset({"*"})
        requires_write_lock = True
        required_for_acceptance = True

        def accepts(self, event, ctx):
            return True

        async def ingest(self, event, ctx):
            raise OSError("disk unavailable")

    with pytest.raises(OSError, match="disk unavailable"):
        await MemoryIngestionMixin()._dispatch_layer(
            RequiredLayer(),
            _memory_event(),
            FanOutContext(),
        )


@pytest.mark.asyncio
async def test_optional_layer_failure_remains_degraded_success() -> None:
    class OptionalLayer:
        layer_name = "optional"
        accepts_event_types = frozenset({"*"})
        requires_write_lock = False
        required_for_acceptance = False

        def accepts(self, event, ctx):
            return True

        async def ingest(self, event, ctx):
            raise RuntimeError("projection unavailable")

    await MemoryIngestionMixin()._dispatch_layer(
        OptionalLayer(),
        _memory_event(),
        FanOutContext(),
    )
