from __future__ import annotations

import pytest

from magi.config import memory_models
from magi.config.models import AppConfig
from magi.config import models as runtime_models
from magi.config.memory_models import MemoryL2Settings


def test_l2_edge_embedding_drain_interval_default():
    cfg = MemoryL2Settings()
    assert cfg.edge_embedding_drain_interval_seconds == 5.0


@pytest.mark.parametrize(
    "model_name",
    [
        "EmbeddingBackend",
        "EmbeddingMode",
        "EmbeddingSettings",
        "EntitySemanticEdgeSettings",
        "GraphSpreadingSettings",
        "LocalEmbeddingModelSource",
        "LocalEmbeddingSettings",
        "MemoryBackend",
        "MemoryHistoryBehavior",
        "MemoryL0Settings",
        "MemoryL1Settings",
        "MemoryL2Settings",
        "MemoryL3Settings",
        "MemoryL4Settings",
        "MemoryRerankerSettings",
        "MemorySettings",
        "QueryExpansionSettings",
    ],
)
def test_runtime_memory_models_reuse_canonical_models(model_name: str):
    assert getattr(runtime_models, model_name) is getattr(memory_models, model_name)


def test_runtime_config_l2_has_derive_schedule_fields():
    l2_cfg = AppConfig().agent.memory.l2

    assert isinstance(l2_cfg, MemoryL2Settings)
    assert l2_cfg.derive_schedule_enabled is True
    assert l2_cfg.derive_schedule_interval_seconds == 21_600.0
    assert l2_cfg.interest_aggregation_enabled is True
    assert l2_cfg.shadow_conflict_notification_enabled is True
