from __future__ import annotations
import pytest
from magi.memory.layer_protocol import (
    FanOutContext,
    LayerIngestResult,
    MemoryLayer,
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
        def accepts(self, e, c): return True
        async def ingest(self, e, c):
            return LayerIngestResult(layer_name="x", ok=True)

    assert isinstance(Dummy(), MemoryLayer)


def test_non_conforming_class_rejected():
    class Bad:
        # missing required attrs
        pass

    assert not isinstance(Bad(), MemoryLayer)
