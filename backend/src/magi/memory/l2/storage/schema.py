"""SQLite schema bootstrap SQL for the L2 cognition store."""

from __future__ import annotations

L2_COGNITION_SCHEMA_SQL = """
                CREATE TABLE IF NOT EXISTS knowledge_graph (
                    triple_id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    fact_kind TEXT NOT NULL DEFAULT 'explicit_fact',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    evidence_event_ids TEXT NOT NULL,
                    evidence_text TEXT DEFAULT '',
                    natural_summary TEXT DEFAULT '',
                    observation_count INTEGER NOT NULL DEFAULT 1,
                    first_observed_at REAL NOT NULL,
                    last_observed_at REAL NOT NULL,
                    last_confirmed_at REAL,
                    source_type TEXT,
                    extraction_method TEXT,
                    embedding_status TEXT DEFAULT 'pending',
                    expires_at REAL,
                    valid_from REAL,
                    valid_to REAL,
                    status TEXT NOT NULL DEFAULT 'active',
                    status_reason TEXT,
                    deprecated_by TEXT,
                    deprecated_at REAL,
                    privacy_scope TEXT NOT NULL DEFAULT 'private',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(subject_id, predicate, object_id)
                );

                CREATE TABLE IF NOT EXISTS entity_facets (
                    facet_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    facet_name TEXT NOT NULL,
                    facet_value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    evidence_event_ids TEXT NOT NULL,
                    first_observed_at REAL NOT NULL,
                    last_observed_at REAL NOT NULL,
                    source_type TEXT,
                    extraction_method TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    privacy_scope TEXT NOT NULL DEFAULT 'private',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(entity_id, facet_name, facet_value)
                );
                CREATE INDEX IF NOT EXISTS idx_entity_facets_entity_name
                    ON entity_facets(entity_id, facet_name);
                CREATE INDEX IF NOT EXISTS idx_entity_facets_name_value
                    ON entity_facets(facet_name, facet_value);

                CREATE INDEX IF NOT EXISTS idx_knowledge_graph_status_subject
                    ON knowledge_graph(status, subject_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_knowledge_graph_status_object
                    ON knowledge_graph(status, object_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_knowledge_graph_status_predicate
                    ON knowledge_graph(status, predicate);

                CREATE TABLE IF NOT EXISTS tom_trait_assertions (
                    assertion_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    trait_family TEXT NOT NULL,
                    trait_name TEXT NOT NULL,
                    trait_value TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    evidence_events TEXT NOT NULL,
                    volatility_index REAL NOT NULL,
                    source_domain TEXT NOT NULL,
                    inference_depth TEXT NOT NULL,
                    validation_state TEXT NOT NULL,
                    first_inferred_at REAL NOT NULL,
                    last_validated_at REAL NOT NULL,
                    target_entity_id TEXT NOT NULL DEFAULT '',
                    target_entity_type TEXT NOT NULL DEFAULT '',
                    target_scope TEXT NOT NULL DEFAULT 'global',
                    temporal_scope TEXT NOT NULL DEFAULT 'session',
                    decay_policy TEXT,
                    decay_anchor_at REAL,
                    context_ref_id TEXT NOT NULL DEFAULT '',
                    expires_at REAL,
                    user_feedback TEXT,
                    user_feedback_at REAL,
                    status TEXT NOT NULL DEFAULT 'active',
                    superseded_by TEXT,
                    superseded_at REAL,
                    privacy_scope TEXT NOT NULL DEFAULT 'private',
                    memory_subdomain TEXT NOT NULL DEFAULT 'state',
                    natural_summary TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tom_assertions_entity_updated
                    ON tom_trait_assertions(entity_id, entity_type, updated_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tom_assertions_active_unique
                    ON tom_trait_assertions(entity_id, entity_type, trait_name, target_entity_id)
                    WHERE status NOT IN ('superseded', 'archived', 'expired', 'user_rejected');

                CREATE TABLE IF NOT EXISTS tom_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    core_traits TEXT,
                    sensitive_triggers TEXT,
                    preferences TEXT,
                    public_sentiment_profile TEXT,
                    relationship_topology TEXT,
                    current_stress_level REAL DEFAULT 0.0,
                    current_mood TEXT,
                    current_engagement REAL DEFAULT 0.5,
                    current_context TEXT,
                    interaction_count INTEGER DEFAULT 0,
                    last_interaction_at REAL,
                    last_updated_at REAL NOT NULL,
                    update_source_assertion_ids TEXT,
                    snapshot_version INTEGER DEFAULT 1,
                    core_traits_history TEXT,
                    preferences_history TEXT,
                    relationship_history TEXT,
                    last_evolution_at REAL,
                    active_record_ids TEXT,
                    superseded_record_ids TEXT,
                    emerging_signals TEXT,
                    mood_trajectory TEXT,
                    created_at REAL NOT NULL,
                    UNIQUE(entity_id, entity_type)
                );

                CREATE TABLE IF NOT EXISTS graph_conflict_rules (
                    predicate TEXT PRIMARY KEY,
                    opposite_predicates TEXT NOT NULL DEFAULT '[]',
                    opposite_resolution TEXT NOT NULL DEFAULT 'mark_deprecated',
                    exclusive_group TEXT,
                    exclusive_scope TEXT NOT NULL DEFAULT 'same_subject',
                    exclusive_resolution TEXT NOT NULL DEFAULT 'mark_deprecated',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS l2_projection_jobs (
                    event_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    batch_owner TEXT,
                    catch_up_owner TEXT,
                    max_events INTEGER,
                    min_ready_events INTEGER,
                    max_wait_seconds REAL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    claimed_by TEXT,
                    claimed_at REAL,
                    started_at REAL,
                    completed_at REAL,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_l2_projection_jobs_status_created
                    ON l2_projection_jobs(status, created_at ASC);

                CREATE INDEX IF NOT EXISTS idx_l2_projection_jobs_owner_status_created
                    ON l2_projection_jobs(batch_owner, status, created_at ASC);

                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    episode_type TEXT NOT NULL DEFAULT 'activity',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    time_start REAL NOT NULL,
                    time_end REAL NOT NULL,
                    parent_episode_id TEXT,
                    label TEXT,
                    summary TEXT,
                    dominant_mode TEXT,
                    primary_entity_ids TEXT NOT NULL DEFAULT '[]',
                    primary_place_ids TEXT NOT NULL DEFAULT '[]',
                    primary_topic_keys TEXT NOT NULL DEFAULT '[]',
                    continuity_signals TEXT NOT NULL DEFAULT '[]',
                    formation_method TEXT NOT NULL DEFAULT 'time_gap_cluster',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    source_event_count INTEGER NOT NULL DEFAULT 0,
                    privacy_scope TEXT NOT NULL DEFAULT 'private',
                    user_label TEXT,
                    user_note TEXT,
                    user_pinned INTEGER NOT NULL DEFAULT 0,
                    embedding_status TEXT NOT NULL DEFAULT 'pending',
                    embedding_profile_id TEXT,
                    last_embedded_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_recomputed_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_episodes_status_time
                    ON episodes(status, time_start DESC);
                CREATE INDEX IF NOT EXISTS idx_episodes_parent
                    ON episodes(parent_episode_id)
                    WHERE parent_episode_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_episodes_type_status
                    ON episodes(episode_type, status);

                CREATE TABLE IF NOT EXISTS episode_events (
                    episode_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    membership_role TEXT NOT NULL DEFAULT 'member',
                    membership_confidence REAL NOT NULL DEFAULT 0.5,
                    added_at REAL NOT NULL,
                    PRIMARY KEY (episode_id, event_id)
                );

                CREATE INDEX IF NOT EXISTS idx_episode_events_event
                    ON episode_events(event_id);


"""
