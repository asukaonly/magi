from __future__ import annotations

import pytest

from magi.config import memory_models
from magi.config.models import AppConfig
from magi.config import models as runtime_models
from magi.config.memory_models import MemoryL2LifecycleSettings, MemoryL2Settings
from magi.memory.l2.entities.maintenance import (
    L2EntityMaintenance,
    L2MaintenanceLifecycle,
)


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
        "MemoryL2LifecycleSettings",
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
    assert l2_cfg.consolidation_enabled is True
    assert l2_cfg.consolidation_interval_seconds == 86_400.0
    assert l2_cfg.derive_schedule_enabled is True
    assert l2_cfg.derive_schedule_interval_seconds == 21_600.0
    assert l2_cfg.interest_aggregation_enabled is True
    assert l2_cfg.shadow_conflict_notification_enabled is True


def test_runtime_config_l2_lifecycle_defaults():
    lifecycle = AppConfig().agent.memory.l2.lifecycle

    assert isinstance(lifecycle, MemoryL2LifecycleSettings)
    assert lifecycle.fast_decay_ttl_seconds == 4 * 3600
    assert lifecycle.session_decay_ttl_seconds == 24 * 3600
    assert lifecycle.archive_confidence_threshold == 0.3
    assert lifecycle.archive_staleness_seconds == 90 * 86400
    assert lifecycle.archive_single_observation_staleness_seconds == 180 * 86400
    assert lifecycle.purge_terminal_edge_staleness_seconds == 365 * 86400
    assert lifecycle.reconcile_stale_threshold_seconds == 3600
    assert lifecycle.reconcile_batch_size == 100
    assert lifecycle.reconcile_max_total == 500
    assert lifecycle.promotion_counter_retention_seconds == 30 * 86400


def test_config_lifecycle_defaults_match_daemon_dataclass():
    """Guard against drift between the config defaults and the daemon defaults."""
    cfg = MemoryL2LifecycleSettings()
    daemon = L2MaintenanceLifecycle()

    assert daemon.fast_decay_ttl_seconds == cfg.fast_decay_ttl_seconds
    assert daemon.session_decay_ttl_seconds == cfg.session_decay_ttl_seconds
    assert daemon.archive_confidence_threshold == cfg.archive_confidence_threshold
    assert daemon.archive_staleness_seconds == cfg.archive_staleness_seconds
    assert (
        daemon.archive_single_observation_staleness_seconds
        == cfg.archive_single_observation_staleness_seconds
    )
    assert daemon.purge_terminal_edge_staleness_seconds == cfg.purge_terminal_edge_staleness_seconds
    assert daemon.reconcile_stale_threshold_seconds == cfg.reconcile_stale_threshold_seconds
    assert daemon.reconcile_batch_size == cfg.reconcile_batch_size
    assert daemon.reconcile_max_total == cfg.reconcile_max_total


def test_maintenance_default_lifecycle_matches_dataclass_defaults():
    maint = L2EntityMaintenance(db_path=":memory:")

    assert maint.FAST_DECAY_TTL == 4 * 3600
    assert maint.SESSION_DECAY_TTL == 24 * 3600
    assert maint.ARCHIVE_CONFIDENCE_THRESHOLD == 0.3
    assert maint.PURGE_TERMINAL_EDGE_STALENESS == 365 * 86400
    assert maint.RECONCILE_BATCH_SIZE == 100


def test_maintenance_honors_lifecycle_overrides():
    lifecycle = L2MaintenanceLifecycle(
        fast_decay_ttl_seconds=120.0,
        session_decay_ttl_seconds=240.0,
        archive_confidence_threshold=0.5,
        reconcile_batch_size=7,
        reconcile_max_total=9,
    )
    maint = L2EntityMaintenance(db_path=":memory:", lifecycle=lifecycle)

    assert maint.FAST_DECAY_TTL == 120.0
    assert maint.SESSION_DECAY_TTL == 240.0
    assert maint.ARCHIVE_CONFIDENCE_THRESHOLD == 0.5
    assert maint.RECONCILE_BATCH_SIZE == 7
    assert maint.RECONCILE_MAX_TOTAL == 9

