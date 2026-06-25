from __future__ import annotations

import pytest

from magi.config import memory_models
from magi.config.models import AppConfig
from magi.config import models as runtime_models
from magi.config.memory_models import (
    MemoryL2ConfidenceSettings,
    MemoryL2EpisodeSettings,
    MemoryL2LifecycleSettings,
    MemoryL2LimitsSettings,
    MemoryL2Settings,
)
from magi.memory.l2.entities.maintenance import (
    L2EntityMaintenance,
    L2MaintenanceLifecycle,
)
from magi.memory.l2.episode_formation import (
    MERGE_GAP_FACTOR,
    MIN_ENTITY_OVERLAP_FOR_MERGE,
    MIN_EVENTS_TO_PROMOTE,
    STANDOUT_DENSE_EVENT_COUNT,
    STANDOUT_MIN_DISTINCT_ENTITIES,
    STANDOUT_MIN_DURATION_SECONDS,
    STANDOUT_MIN_EVENTS,
    StandoutGate,
    _passes_standout_gate,
)
from magi.memory.l2.storage.utils import (
    CONFIDENCE_ACCUMULATION_CAP,
    MAX_EVIDENCE_EVENT_IDS,
    MOOD_TRAJECTORY_LIMIT,
    SINGLE_EVENT_CONFIDENCE_CAP,
    SNAPSHOT_HISTORY_LIMIT,
    confidence_accumulation_cap,
    max_evidence_event_ids,
    mood_trajectory_limit,
    single_event_confidence_cap,
    snapshot_history_limit,
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
        "MemoryL2ConfidenceSettings",
        "MemoryL2EpisodeSettings",
        "MemoryL2LifecycleSettings",
        "MemoryL2LimitsSettings",
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


def test_runtime_config_l2_limits_defaults():
    limits = AppConfig().agent.memory.l2.limits

    assert isinstance(limits, MemoryL2LimitsSettings)
    assert limits.snapshot_history_limit == 5
    assert limits.mood_trajectory_limit == 20
    assert limits.max_evidence_event_ids == 50


def test_l2_limits_config_defaults_match_module_constants():
    """Guard against drift between config defaults and the module fallback constants."""
    limits = MemoryL2LimitsSettings()

    assert limits.snapshot_history_limit == SNAPSHOT_HISTORY_LIMIT
    assert limits.mood_trajectory_limit == MOOD_TRAJECTORY_LIMIT
    assert limits.max_evidence_event_ids == MAX_EVIDENCE_EVENT_IDS


def test_runtime_config_l2_confidence_defaults():
    confidence = AppConfig().agent.memory.l2.confidence

    assert isinstance(confidence, MemoryL2ConfidenceSettings)
    assert confidence.accumulation_cap == 0.99
    assert confidence.single_event_cap == 0.3


def test_l2_confidence_config_defaults_match_module_constants():
    confidence = MemoryL2ConfidenceSettings()

    assert confidence.accumulation_cap == CONFIDENCE_ACCUMULATION_CAP
    assert confidence.single_event_cap == SINGLE_EVENT_CONFIDENCE_CAP


def test_l2_limit_accessors_fall_back_when_config_unavailable(monkeypatch):
    """The user-facing guarantee: defaults still apply when no config resolves."""
    import magi.config

    def _boom() -> object:
        raise RuntimeError("no config bound")

    monkeypatch.setattr(magi.config, "get_config", _boom)

    assert snapshot_history_limit() == SNAPSHOT_HISTORY_LIMIT
    assert mood_trajectory_limit() == MOOD_TRAJECTORY_LIMIT
    assert max_evidence_event_ids() == MAX_EVIDENCE_EVENT_IDS
    assert confidence_accumulation_cap() == CONFIDENCE_ACCUMULATION_CAP
    assert single_event_confidence_cap() == SINGLE_EVENT_CONFIDENCE_CAP


def test_l2_limit_accessors_read_config_overrides(monkeypatch):
    import magi.config

    cfg = AppConfig()
    cfg.agent.memory.l2.limits.snapshot_history_limit = 9
    cfg.agent.memory.l2.limits.mood_trajectory_limit = 42
    cfg.agent.memory.l2.limits.max_evidence_event_ids = 7
    cfg.agent.memory.l2.confidence.accumulation_cap = 0.5
    cfg.agent.memory.l2.confidence.single_event_cap = 0.1
    monkeypatch.setattr(magi.config, "get_config", lambda: cfg)

    assert snapshot_history_limit() == 9
    assert mood_trajectory_limit() == 42
    assert max_evidence_event_ids() == 7
    assert confidence_accumulation_cap() == 0.5
    assert single_event_confidence_cap() == 0.1


def test_accumulate_confidence_honors_configured_cap(monkeypatch):
    import magi.config
    from magi.memory.l2.storage.utils import accumulate_confidence

    cfg = AppConfig()
    cfg.agent.memory.l2.confidence.accumulation_cap = 0.5
    monkeypatch.setattr(magi.config, "get_config", lambda: cfg)

    # Noisy-OR of 0.9 and 0.9 is 0.99, but the configured cap clamps it to 0.5.
    assert accumulate_confidence(0.9, 0.9) == 0.5


def test_runtime_config_l2_episode_defaults():
    episode = AppConfig().agent.memory.l2.episode

    assert isinstance(episode, MemoryL2EpisodeSettings)
    assert episode.min_events_to_promote == 3
    assert episode.min_age_to_promote_seconds == 30 * 60
    assert episode.merge_gap_factor == 1.5
    assert episode.min_entity_overlap_for_merge == 0.3
    assert episode.standout_min_events == 8
    assert episode.standout_min_duration_seconds == 45 * 60
    assert episode.standout_dense_event_count == 20
    assert episode.standout_min_distinct_entities == 2


def test_l2_episode_config_defaults_match_module_constants():
    episode = MemoryL2EpisodeSettings()

    assert episode.min_events_to_promote == MIN_EVENTS_TO_PROMOTE
    assert episode.merge_gap_factor == MERGE_GAP_FACTOR
    assert episode.min_entity_overlap_for_merge == MIN_ENTITY_OVERLAP_FOR_MERGE
    assert episode.standout_min_events == STANDOUT_MIN_EVENTS
    assert episode.standout_min_duration_seconds == STANDOUT_MIN_DURATION_SECONDS
    assert episode.standout_dense_event_count == STANDOUT_DENSE_EVENT_COUNT
    assert episode.standout_min_distinct_entities == STANDOUT_MIN_DISTINCT_ENTITIES


def test_standout_gate_default_matches_module_constants():
    gate = StandoutGate()

    assert gate.min_events == STANDOUT_MIN_EVENTS
    assert gate.min_duration_seconds == STANDOUT_MIN_DURATION_SECONDS
    assert gate.dense_event_count == STANDOUT_DENSE_EVENT_COUNT
    assert gate.min_distinct_entities == STANDOUT_MIN_DISTINCT_ENTITIES


def test_standout_gate_from_config_falls_back_without_config(monkeypatch):
    import magi.config

    def _boom() -> object:
        raise RuntimeError("no config bound")

    monkeypatch.setattr(magi.config, "get_config", _boom)

    assert StandoutGate.from_config() == StandoutGate()


def test_standout_gate_from_config_reads_override(monkeypatch):
    import magi.config

    cfg = AppConfig()
    cfg.agent.memory.l2.episode.standout_min_events = 2
    monkeypatch.setattr(magi.config, "get_config", lambda: cfg)

    gate = StandoutGate.from_config()
    assert gate.min_events == 2
    # A 2-event, rich-enough episode now passes the lowered gate.
    episode = {
        "source_event_count": 2,
        "time_start": 0.0,
        "time_end": 60 * 60.0,
        "primary_entity_ids": ["a", "b"],
    }
    assert _passes_standout_gate(episode, gate) is True




