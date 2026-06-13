from __future__ import annotations
from magi.config.memory_models import MemoryL2Settings


def test_l2_edge_embedding_drain_interval_default():
    cfg = MemoryL2Settings()
    assert cfg.edge_embedding_drain_interval_seconds == 5.0
