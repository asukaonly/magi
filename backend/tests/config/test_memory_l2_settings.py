from __future__ import annotations

import pytest

from magi.config import memory_models
from magi.config.models import AppConfig
from magi.config import models as runtime_models
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
        "MemoryL2AssertionSettings",
        "MemoryL2ConfidenceSettings",
        "MemoryL2EpisodeSettings",
        "MemoryL2ExperienceSettings",
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


def test_runtime_lifecycle_defaults_match_daemon_fallback():
    from dataclasses import asdict

    fallback = asdict(L2MaintenanceLifecycle())
    runtime = AppConfig().agent.memory.l2.lifecycle.model_dump()
    assert {key: runtime[key] for key in fallback} == fallback


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overridden", [False, True], ids=["defaults-retain", "overrides-expire-and-archive"]
)
async def test_maintenance_lifecycle_settings_change_persisted_selection(
    tmp_path, overridden, monkeypatch
):
    from types import SimpleNamespace
    import aiosqlite
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.entities.maintenance import L2EntityMaintenanceStats
    from magi.memory.l2.entities.maintenance import assertions, edges

    now = 2_000_000_000.0
    monkeypatch.setattr(assertions, "time", SimpleNamespace(time=lambda: now))
    monkeypatch.setattr(edges, "time", SimpleNamespace(time=lambda: now))
    store = L2CognitionStore(db_path=str(tmp_path / "memory.db"))
    await store.initialize()
    assertion_ids = {}
    for name, decay, age in [
        ("old-fast", "fast_decay", 180),
        ("recent-fast", "fast_decay", 60),
        ("old-session", "session_decay", 300),
        ("recent-session", "session_decay", 200),
        ("durable", "no_decay", 500000),
    ]:
        assertion_ids[name] = await store.upsert_assertion_candidate(
            {
                "entity_id": f"user:{name}",
                "entity_type": "user",
                "trait_family": "mood",
                "trait_name": name,
                "trait_value": "high",
                "confidence_score": 0.25,
                "volatility_index": 0.7,
                "source_domain": "chat",
                "inference_depth": "defensive_psychology",
                "validation_state": "tentative",
                "decay_policy": decay,
                "evidence_events": [f"e-{name}"],
                "first_inferred_at": now - age,
                "last_validated_at": now - age,
            }
        )
        async with aiosqlite.connect(store.db_path) as db:
            await db.execute(
                "UPDATE tom_trait_assertions SET updated_at = ?, expires_at = NULL, decay_policy = ? WHERE assertion_id = ?",
                (now - age, decay, assertion_ids[name]),
            )
            await db.commit()
    edge_ids = {}
    for name, confidence, age in [
        ("stale-low", 0.4, 100 * 86400),
        ("stale-high", 0.6, 100 * 86400),
        ("fresh-low", 0.4, 86400),
    ]:
        edge_ids[name] = await store.upsert_knowledge_edge(
            subject_id="user:u1",
            subject_type="user",
            predicate="LIKES",
            object_id=f"topic:{name}",
            object_type="topic",
            confidence=confidence,
            evidence_event_ids=[f"e-{name}-1", f"e-{name}-2"],
            observed_at=now - age,
            source_type="chat",
            evidence_class="model_inference",
        )
        async with aiosqlite.connect(store.db_path) as db:
            await db.execute(
                "UPDATE knowledge_graph SET confidence = ?, observation_count = 2, updated_at = ? WHERE triple_id = ?",
                (confidence, now - age, edge_ids[name]),
            )
            await db.commit()
    lifecycle = (
        L2MaintenanceLifecycle(
            fast_decay_ttl_seconds=120,
            session_decay_ttl_seconds=240,
            archive_confidence_threshold=0.5,
            reconcile_batch_size=7,
            reconcile_max_total=9,
        )
        if overridden
        else None
    )
    maintenance = L2EntityMaintenance(db_path=store.db_path, lifecycle=lifecycle)
    if overridden:
        assert (maintenance.RECONCILE_BATCH_SIZE, maintenance.RECONCILE_MAX_TOTAL) == (7, 9)
    stats = L2EntityMaintenanceStats()
    await maintenance._expire_decayed_assertions(stats)
    await maintenance._archive_stale_edges(stats)
    async with aiosqlite.connect(store.db_path) as db:
        cursor = await db.execute(
            "SELECT assertion_id FROM tom_trait_assertions WHERE validation_state = 'expired'"
        )
        expired = {row[0] for row in await cursor.fetchall()}
        cursor = await db.execute("SELECT triple_id FROM knowledge_graph WHERE status = 'archived'")
        archived = {row[0] for row in await cursor.fetchall()}
    assert expired == (
        {assertion_ids["old-fast"], assertion_ids["old-session"]} if overridden else set()
    )
    assert archived == ({edge_ids["stale-low"]} if overridden else set())
    assert (stats.expired_assertions, stats.edges_archived) == ((2, 1) if overridden else (0, 0))


def test_l2_limits_config_defaults_match_module_constants():
    """Guard against drift between config defaults and the module fallback constants."""
    limits = AppConfig().agent.memory.l2.limits

    assert limits.snapshot_history_limit == SNAPSHOT_HISTORY_LIMIT
    assert limits.mood_trajectory_limit == MOOD_TRAJECTORY_LIMIT
    assert limits.max_evidence_event_ids == MAX_EVIDENCE_EVENT_IDS


def test_l2_confidence_config_defaults_match_module_constants():
    confidence = AppConfig().agent.memory.l2.confidence

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


def test_l2_episode_config_defaults_match_module_constants():
    episode = AppConfig().agent.memory.l2.episode

    assert episode.min_events_to_promote == MIN_EVENTS_TO_PROMOTE
    assert episode.merge_gap_factor == MERGE_GAP_FACTOR
    assert episode.min_entity_overlap_for_merge == MIN_ENTITY_OVERLAP_FOR_MERGE
    assert episode.standout_min_events == STANDOUT_MIN_EVENTS
    assert episode.standout_min_duration_seconds == STANDOUT_MIN_DURATION_SECONDS
    assert episode.standout_dense_event_count == STANDOUT_DENSE_EVENT_COUNT
    assert episode.standout_min_distinct_entities == STANDOUT_MIN_DISTINCT_ENTITIES

    gate = StandoutGate()
    assert (
        gate.min_events,
        gate.min_duration_seconds,
        gate.dense_event_count,
        gate.min_distinct_entities,
    ) == (
        episode.standout_min_events,
        episode.standout_min_duration_seconds,
        episode.standout_dense_event_count,
        episode.standout_min_distinct_entities,
    )


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


def test_l2_experience_config_defaults_match_module_constants():
    from magi.memory.l2.experiences.promotion import DUPLICATE_OVERLAP_RATIO
    from magi.memory.l2.experiences.quality import MIN_EXPERIENCE_QUALITY_SCORE
    from magi.memory.l2.experiences.seed_discovery import (
        MAX_REPEATED_GOAL_GAP_SECONDS,
        MAX_REPEATED_GOAL_WINDOW_SECONDS,
        MIN_REPEATED_GOAL_EPISODES,
        MIN_REPEATED_GOAL_EVENTS,
    )

    experience = AppConfig().agent.memory.l2.experience

    assert experience.min_quality_score == MIN_EXPERIENCE_QUALITY_SCORE
    assert experience.duplicate_overlap_ratio == DUPLICATE_OVERLAP_RATIO
    assert experience.min_repeated_goal_episodes == MIN_REPEATED_GOAL_EPISODES
    assert experience.min_repeated_goal_events == MIN_REPEATED_GOAL_EVENTS
    assert experience.max_repeated_goal_window_seconds == MAX_REPEATED_GOAL_WINDOW_SECONDS
    assert experience.max_repeated_goal_gap_seconds == MAX_REPEATED_GOAL_GAP_SECONDS


def test_l2_assertion_config_defaults_match_module_constants():
    from magi.memory.l2.assertions.state_machine import (
        CONFIDENCE_BASE,
        CONFIDENCE_CEILING,
        CONFIDENCE_SLOPE,
        CORROBORATED_CONFIDENCE_FLOOR,
        CORROBORATED_EVIDENCE_COUNT,
        CONTRADICTED_CONFIDENCE_CEILING,
        EXPIRED_CONFIDENCE_CEILING,
        STABLE_EVIDENCE_COUNT,
        STABLE_CONFIDENCE_FLOOR,
        STABLE_TIME_SPAN_HOURS,
        TEMPORARY_CORROBORATED_CONFIDENCE_FLOOR,
        TENTATIVE_CONFIDENCE_CEILING,
        USER_CONFIRMED_CONFIDENCE_FLOOR,
        USER_REJECTED_CONFIDENCE,
    )
    from magi.memory.l2.assertions.settings import (
        ENGAGEMENT_TTL_SECONDS,
        GROUP_SENTIMENT_TTL_SECONDS,
        MOMENTARY_TTL_SECONDS,
        MOOD_TTL_SECONDS,
        STRESS_TTL_SECONDS,
    )

    assertion = AppConfig().agent.memory.l2.assertion

    assert assertion.confidence_base == CONFIDENCE_BASE
    assert assertion.confidence_slope == CONFIDENCE_SLOPE
    assert assertion.confidence_ceiling == CONFIDENCE_CEILING
    assert assertion.stable_evidence_count == STABLE_EVIDENCE_COUNT
    assert assertion.stable_time_span_hours == STABLE_TIME_SPAN_HOURS
    assert assertion.corroborated_evidence_count == CORROBORATED_EVIDENCE_COUNT
    assert assertion.user_rejected_confidence == USER_REJECTED_CONFIDENCE
    assert assertion.user_confirmed_confidence_floor == USER_CONFIRMED_CONFIDENCE_FLOOR
    assert assertion.expired_confidence_ceiling == EXPIRED_CONFIDENCE_CEILING
    assert assertion.contradicted_confidence_ceiling == CONTRADICTED_CONFIDENCE_CEILING
    assert assertion.stable_confidence_floor == STABLE_CONFIDENCE_FLOOR
    assert (
        assertion.temporary_corroborated_confidence_floor == TEMPORARY_CORROBORATED_CONFIDENCE_FLOOR
    )
    assert assertion.corroborated_confidence_floor == CORROBORATED_CONFIDENCE_FLOOR
    assert assertion.tentative_confidence_ceiling == TENTATIVE_CONFIDENCE_CEILING
    assert assertion.momentary_ttl_seconds == MOMENTARY_TTL_SECONDS
    assert assertion.mood_ttl_seconds == MOOD_TTL_SECONDS
    assert assertion.stress_ttl_seconds == STRESS_TTL_SECONDS
    assert assertion.engagement_ttl_seconds == ENGAGEMENT_TTL_SECONDS
    assert assertion.group_sentiment_ttl_seconds == GROUP_SENTIMENT_TTL_SECONDS


def test_compute_confidence_falls_back_without_config(monkeypatch):
    import magi.config
    from magi.memory.l2.assertions.state_machine import compute_confidence

    def _boom() -> object:
        raise RuntimeError("no config bound")

    monkeypatch.setattr(magi.config, "get_config", _boom)

    # Default curve: 0.3 + 0.25*(n-1), capped at 0.95.
    assert compute_confidence(1) == 0.3
    assert compute_confidence(3) == 0.8


def test_compute_confidence_reads_config_override(monkeypatch):
    import magi.config
    from magi.memory.l2.assertions.state_machine import compute_confidence

    cfg = AppConfig()
    cfg.agent.memory.l2.assertion.confidence_base = 0.5
    cfg.agent.memory.l2.assertion.confidence_slope = 0.1
    cfg.agent.memory.l2.assertion.confidence_ceiling = 0.6
    monkeypatch.setattr(magi.config, "get_config", lambda: cfg)

    assert compute_confidence(1) == 0.5
    assert compute_confidence(2) == pytest.approx(0.6)  # 0.5 + 0.1, at ceiling
    assert compute_confidence(5) == 0.6  # clamped to ceiling


def test_derive_validation_state_honors_graduation_gate_override(monkeypatch):
    import magi.config
    from magi.memory.l2.assertions.state_machine import derive_validation_state

    cfg = AppConfig()
    cfg.agent.memory.l2.assertion.stable_evidence_count = 2
    cfg.agent.memory.l2.assertion.stable_time_span_hours = 1.0
    monkeypatch.setattr(magi.config, "get_config", lambda: cfg)

    state, _confidence, _kind = derive_validation_state(
        current_state="corroborated",
        current_confidence=0.6,
        evidence_count=2,
        time_span_hours=1.0,
        trait_name="preference.coffee",
    )
    assert state == "stable"


def test_derive_validation_state_honors_state_threshold_overrides(monkeypatch):
    import magi.config
    from magi.memory.l2.assertions.state_machine import derive_validation_state

    cfg = AppConfig()
    cfg.agent.memory.l2.assertion.stable_confidence_floor = 0.91
    cfg.agent.memory.l2.assertion.contradicted_confidence_ceiling = 0.22
    cfg.agent.memory.l2.assertion.user_rejected_confidence = 0.04
    monkeypatch.setattr(magi.config, "get_config", lambda: cfg)

    stable_state, stable_confidence, _kind = derive_validation_state(
        current_state="tentative",
        current_confidence=0.6,
        evidence_count=3,
        time_span_hours=24.0,
        trait_name="preference.coffee",
    )
    assert stable_state == "stable"
    assert stable_confidence == 0.91

    contradicted_state, contradicted_confidence, _kind = derive_validation_state(
        current_state="contradicted",
        current_confidence=0.8,
        evidence_count=3,
        time_span_hours=24.0,
        trait_name="preference.coffee",
    )
    assert contradicted_state == "contradicted"
    assert contradicted_confidence == 0.22

    rejected_state, rejected_confidence, _kind = derive_validation_state(
        current_state="tentative",
        current_confidence=0.8,
        evidence_count=3,
        time_span_hours=24.0,
        trait_name="preference.coffee",
        user_feedback="rejected",
    )
    assert rejected_state == "user_rejected"
    assert rejected_confidence == 0.04


def test_contradiction_confidence_honors_state_threshold_overrides(monkeypatch):
    import magi.config
    from magi.memory.l2.assertions.reconcile_state import L2ReconcileStateMixin

    cfg = AppConfig()
    cfg.agent.memory.l2.assertion.contradicted_confidence_ceiling = 0.22
    cfg.agent.memory.l2.assertion.user_rejected_confidence = 0.04
    monkeypatch.setattr(magi.config, "get_config", lambda: cfg)

    mixin = L2ReconcileStateMixin()

    assert mixin._contradicted_confidence(
        current_confidence=0.9,
        hint_confidence=1.0,
        action="downgrade_confidence",
    ) == 0.22
    assert mixin._contradicted_confidence(
        current_confidence=0.1,
        hint_confidence=1.0,
        action="mark_conflicted",
    ) == 0.04


def test_host_assertion_decay_reads_configured_family_ttl(monkeypatch):
    import magi.config
    from magi.memory.l2.assertion_family_policy import get_assertion_family_policy
    from magi.memory.l2.assertions.reconcile_state import L2ReconcileStateMixin

    cfg = AppConfig()
    cfg.agent.memory.l2.assertion.momentary_ttl_seconds = 45.0
    cfg.agent.memory.l2.assertion.mood_ttl_seconds = 123.0
    monkeypatch.setattr(magi.config, "get_config", lambda: cfg)

    mood = get_assertion_family_policy("mood")
    assert mood is not None
    assert mood.default_temporal_scope == "session"
    assert mood.default_decay_policy == "session_decay"
    assert mood.default_ttl_seconds == 123.0

    expires_at = L2ReconcileStateMixin()._coerce_expires_at(
        None,
        trait_family="mood",
        trait_name="annoyance",
        target_entity_id="person:alice",
        anchor_at=1000.0,
    )

    assert expires_at == 1045.0
