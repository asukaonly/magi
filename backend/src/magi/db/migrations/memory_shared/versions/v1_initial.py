"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS l0_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT,
    runtime_agent_id TEXT,
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    last_active_at REAL NOT NULL,
    last_checkpoint_at REAL,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS l0_goal_stack (
    stack_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    parent_goal_id TEXT,
    goal_type TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    result_summary TEXT,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS l0_active_entities (
    session_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    relevance_score REAL DEFAULT 0.0,
    snapshot_json TEXT NOT NULL,
    loaded_at REAL NOT NULL,
    last_accessed_at REAL NOT NULL,
    access_count INTEGER DEFAULT 0,
    PRIMARY KEY (session_id, entity_id, entity_type)
);

CREATE TABLE IF NOT EXISTS l0_temporary_tactics (
    tactic_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    tactic_type TEXT NOT NULL,
    tactic_payload TEXT NOT NULL,
    source_event_ids TEXT NOT NULL,
    expires_at REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS l0_execution_runs (
    session_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    root_turn_id TEXT,
    root_user_message TEXT NOT NULL,
    response_anchor_turn_id TEXT,
    cancel_requested_at REAL,
    cancel_reason TEXT,
    cancel_requested_by TEXT,
    cancel_anchor_turn_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    trigger_json TEXT
);

CREATE TABLE IF NOT EXISTS l0_execution_pending_turns (
    pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    content TEXT NOT NULL,
    revision INTEGER NOT NULL,
    disposition TEXT NOT NULL DEFAULT 'augment',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS l0_execution_results (
    result_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    disposition TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

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
    embedding_profile_id TEXT,
    last_embedded_at REAL,
    expires_at REAL,
    valid_from REAL,
    valid_to REAL,
    status TEXT NOT NULL DEFAULT 'active',
    status_reason TEXT,
    deprecated_by TEXT,
    deprecated_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    evidence_class TEXT DEFAULT NULL,
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
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(entity_id, facet_name, facet_value)
);

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
    memory_subdomain TEXT NOT NULL DEFAULT 'state',
    natural_summary TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

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
    user_label TEXT,
    user_note TEXT,
    user_pinned INTEGER NOT NULL DEFAULT 0,
    embedding_status TEXT NOT NULL DEFAULT 'pending',
    embedding_profile_id TEXT,
    last_embedded_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_recomputed_at REAL,
    slice_narrative TEXT,
    slice_sensory_detail TEXT,
    magi_standout INTEGER NOT NULL DEFAULT 0,
    standout_score REAL NOT NULL DEFAULT 0.0,
    standout_reason TEXT,
    representative_asset_ref TEXT
);

CREATE TABLE IF NOT EXISTS episode_events (
    episode_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    membership_role TEXT NOT NULL DEFAULT 'member',
    membership_confidence REAL NOT NULL DEFAULT 0.5,
    added_at REAL NOT NULL,
    PRIMARY KEY (episode_id, event_id)
);

CREATE TABLE IF NOT EXISTS summaries (
    summary_id TEXT PRIMARY KEY,
    summary_type TEXT NOT NULL,
    summary_category TEXT NOT NULL,
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,
    content TEXT NOT NULL,
    key_topics TEXT,
    key_entities TEXT,
    sentiment_summary TEXT,
    change_and_pattern TEXT,
    source_event_ids TEXT NOT NULL,
    source_event_count INTEGER NOT NULL,
    importance_aggregate REAL,
    event_type_distribution TEXT,
    generated_by_model TEXT,
    generation_prompt TEXT,
    generation_reason TEXT,
    insight_key TEXT,
    review_state TEXT,
    insight_metadata TEXT,
    embedding_status TEXT NOT NULL DEFAULT 'disabled',
    embedding_profile_id TEXT,
    embedding_chunk_count INTEGER NOT NULL DEFAULT 0,
    last_embedded_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    narrative_style TEXT NOT NULL DEFAULT 'default',
    essence_prose TEXT
);

CREATE TABLE IF NOT EXISTS summary_event_links (
    link_id TEXT PRIMARY KEY,
    summary_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    link_role TEXT NOT NULL,
    evidence_weight REAL NOT NULL DEFAULT 1.0,
    created_at REAL NOT NULL,
    UNIQUE(summary_id, event_id, link_role)
);

CREATE TABLE IF NOT EXISTS summary_task_links (
    link_id TEXT PRIMARY KEY,
    summary_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    link_role TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(summary_id, task_id, link_role)
);

CREATE TABLE IF NOT EXISTS l3_summary_chunks (
    chunk_id TEXT PRIMARY KEY,
    summary_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    token_estimate INTEGER NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS l3_summaries_fts USING fts5(
    summary_id UNINDEXED,
    content,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS procedural_skills (
    skill_id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    skill_category TEXT NOT NULL,
    skill_type TEXT NOT NULL,
    proficiency REAL NOT NULL DEFAULT 0.0,
    total_attempts INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    success_rate REAL NOT NULL DEFAULT 0.0,
    avg_execution_time_ms REAL,
    min_execution_time_ms REAL,
    max_execution_time_ms REAL,
    p95_execution_time_ms REAL,
    circuit_breaker_state TEXT NOT NULL DEFAULT 'closed',
    circuit_breaker_opened_at REAL,
    circuit_breaker_failure_count INTEGER NOT NULL DEFAULT 0,
    circuit_breaker_success_count INTEGER NOT NULL DEFAULT 0,
    optimized_prompt TEXT,
    optimized_params TEXT,
    optimization_score REAL,
    context_affinity TEXT,
    source_event_ids TEXT NOT NULL,
    last_used_at REAL,
    last_success_at REAL,
    last_failure_at REAL,
    embedding_status TEXT NOT NULL DEFAULT 'disabled',
    embedding_profile_id TEXT,
    embedding_chunk_count INTEGER NOT NULL DEFAULT 0,
    last_embedded_at REAL,
    pending_trace_count INTEGER NOT NULL DEFAULT 0,
    deleted_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(skill_name, skill_category)
);

CREATE TABLE IF NOT EXISTS l4_skill_chunks (
    chunk_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    token_estimate INTEGER NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS l4_skills_fts USING fts5(
    skill_id UNINDEXED,
    content,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS l4_execution_traces (
    trace_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    turn_id TEXT,
    success INTEGER NOT NULL,
    duration_ms REAL,
    error_summary TEXT,
    input_summary TEXT,
    output_summary TEXT,
    task_context TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_catalog (
    entity_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    embedding_status TEXT NOT NULL DEFAULT 'disabled',
    embedding_profile_id TEXT,
    last_embedded_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    alias_text TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(entity_id, normalized_alias),
    FOREIGN KEY(entity_id) REFERENCES entity_catalog(entity_id)
);

CREATE TABLE IF NOT EXISTS entity_mentions (
    mention_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mention_text TEXT NOT NULL,
    normalized_surface TEXT NOT NULL,
    entity_type TEXT,
    evidence_event_ids TEXT NOT NULL,
    evidence_text TEXT,
    resolved_entity_id TEXT,
    confidence REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY(resolved_entity_id) REFERENCES entity_catalog(entity_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    episode_id,
    summary,
    label,
    user_label
);

CREATE TABLE IF NOT EXISTS embedding_rebuild_jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    requested_layers_json TEXT NOT NULL,
    active_layer TEXT,
    total_items INTEGER NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    succeeded_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_rebuild_job_layers (
    job_id TEXT NOT NULL,
    layer TEXT NOT NULL,
    status TEXT NOT NULL,
    total_items INTEGER NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    succeeded_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at REAL,
    finished_at REAL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (job_id, layer)
);

CREATE TABLE IF NOT EXISTS user_profile_projection (
    user_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    preferred_form_of_address TEXT NOT NULL DEFAULT '',
    real_name TEXT NOT NULL DEFAULT '',
    birth_date TEXT NOT NULL DEFAULT '',
    birth_year INTEGER,
    age_years INTEGER,
    age_as_of TEXT NOT NULL DEFAULT '',
    home_location TEXT NOT NULL DEFAULT '',
    communication_json TEXT NOT NULL DEFAULT '{}',
    identity_json TEXT NOT NULL DEFAULT '{}',
    preferences_json TEXT NOT NULL DEFAULT '{}',
    state_json TEXT NOT NULL DEFAULT '{}',
    field_sources_json TEXT NOT NULL DEFAULT '{}',
    field_conflicts_json TEXT NOT NULL DEFAULT '{}',
    completeness_score REAL NOT NULL DEFAULT 0,
    refreshed_at REAL NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_mood_aggregate (
    day_local_date TEXT PRIMARY KEY,
    dominant_valence TEXT NOT NULL DEFAULT 'neutral',
    volatility_score REAL NOT NULL DEFAULT 0.0,
    state_curve_compact TEXT NOT NULL DEFAULT '[]',
    event_count INTEGER NOT NULL DEFAULT 0,
    computed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS location_samples (
    sample_id      TEXT PRIMARY KEY,
    source         TEXT NOT NULL,
    sampled_at     REAL NOT NULL,
    lat            REAL,
    lng            REAL,
    accuracy_m     REAL,
    city           TEXT,
    region         TEXT,
    country        TEXT,
    metadata_json  TEXT NOT NULL DEFAULT '{}',
    created_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS place_geocode_cache (
    grid_key   TEXT PRIMARY KEY,
    city       TEXT,
    region     TEXT,
    country    TEXT,
    poi_name   TEXT,
    cached_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS place_labels (
    label_id    TEXT PRIMARY KEY,
    center_lat  REAL NOT NULL,
    center_lng  REAL NOT NULL,
    radius_m    REAL NOT NULL DEFAULT 100.0,
    user_label  TEXT NOT NULL,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_entries (
    entry_id          TEXT PRIMARY KEY,
    created_at        REAL NOT NULL,
    event_at          REAL NOT NULL,
    kind              TEXT NOT NULL DEFAULT 'quick',
    body              TEXT NOT NULL,
    mood              TEXT,
    location_label    TEXT,
    location_lat      REAL,
    location_lng      REAL,
    attachments_json  TEXT NOT NULL DEFAULT '[]',
    exclude_from_llm  INTEGER NOT NULL DEFAULT 0,
    user_pinned       INTEGER NOT NULL DEFAULT 0,
    deleted_at        REAL,
    l1_event_id       TEXT,
    weather_json TEXT,
    body_doc TEXT
);

CREATE TABLE IF NOT EXISTS experiences (
    experience_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'candidate',
    title TEXT,
    time_start REAL NOT NULL,
    time_end REAL NOT NULL,
    experience_type TEXT,
    intent TEXT,
    outcome TEXT,
    magi_interpretation TEXT,
    narrative_score REAL NOT NULL DEFAULT 0.0,
    primary_entity_ids TEXT NOT NULL DEFAULT '[]',
    primary_place_ids TEXT NOT NULL DEFAULT '[]',
    primary_topic_keys TEXT NOT NULL DEFAULT '[]',
    source_episode_count INTEGER NOT NULL DEFAULT 0,
    source_event_count INTEGER NOT NULL DEFAULT 0,
    parent_experience_id TEXT,
    merged_into_experience_id TEXT,
    user_label TEXT,
    user_note TEXT,
    user_pinned INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_recomputed_at REAL,
    source_seed_id TEXT,
    user_cover_asset_ref TEXT
);

CREATE TABLE IF NOT EXISTS experience_members (
    experience_id TEXT NOT NULL,
    member_type TEXT NOT NULL,
    member_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'core',
    confidence REAL NOT NULL DEFAULT 0.5,
    added_at REAL NOT NULL,
    PRIMARY KEY (experience_id, member_type, member_id)
);

CREATE TABLE IF NOT EXISTS experience_key_events (
    experience_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    role TEXT NOT NULL,
    reason TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    added_at REAL NOT NULL,
    PRIMARY KEY (experience_id, event_id, role)
);

CREATE TABLE IF NOT EXISTS experience_seeds (
            seed_id TEXT PRIMARY KEY,
            seed_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'candidate',
            title TEXT,
            description TEXT,
            anchor_entity_ids TEXT NOT NULL DEFAULT '[]',
            anchor_place_ids TEXT NOT NULL DEFAULT '[]',
            anchor_topic_keys TEXT NOT NULL DEFAULT '[]',
            time_start REAL,
            time_end REAL,
            confidence REAL NOT NULL DEFAULT 0.0,
            created_by TEXT NOT NULL DEFAULT 'system',
            source_ref_type TEXT,
            source_ref_id TEXT,
            promoted_experience_id TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            last_evaluated_at REAL
        );

CREATE TABLE IF NOT EXISTS experience_seed_evidence (
            seed_id TEXT NOT NULL,
            ref_type TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'support',
            confidence REAL NOT NULL DEFAULT 0.5,
            reason TEXT,
            created_at REAL NOT NULL,
            PRIMARY KEY (seed_id, ref_type, ref_id, role)
        );

CREATE TABLE IF NOT EXISTS experience_drafts (
    draft_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'editing',
    query_text TEXT NOT NULL,
    title TEXT NOT NULL,
    one_sentence_review TEXT NOT NULL,
    time_start REAL NOT NULL,
    time_end REAL NOT NULL,
    chapters_json TEXT NOT NULL DEFAULT '[]',
    possible_evidence_json TEXT NOT NULL DEFAULT '[]',
    excluded_evidence_json TEXT NOT NULL DEFAULT '[]',
    created_experience_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS experience_chapters (
    experience_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    time_start REAL,
    time_end REAL,
    episode_ids_json TEXT NOT NULL DEFAULT '[]',
    event_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (experience_id, chapter_id)
);

CREATE TABLE IF NOT EXISTS user_portrait_projection (
    user_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'user',
    world_json TEXT NOT NULL DEFAULT '{}',
    review_json TEXT NOT NULL DEFAULT '{}',
    recent_json TEXT NOT NULL DEFAULT '{}',
    prompt_summary_json TEXT NOT NULL DEFAULT '[]',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    source_counts_json TEXT NOT NULL DEFAULT '{}',
    generated_by TEXT NOT NULL DEFAULT 'rule',
    generated_at REAL NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entity_facets_name_value
    ON entity_facets(facet_name, facet_value);

CREATE INDEX IF NOT EXISTS idx_knowledge_graph_status_subject
    ON knowledge_graph(status, subject_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_knowledge_graph_status_object
    ON knowledge_graph(status, object_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_knowledge_graph_status_predicate
    ON knowledge_graph(status, predicate);

CREATE INDEX IF NOT EXISTS idx_knowledge_graph_embedding_profile
    ON knowledge_graph(embedding_profile_id);

CREATE INDEX IF NOT EXISTS idx_tom_assertions_entity_updated
    ON tom_trait_assertions(entity_id, entity_type, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_l2_projection_jobs_status_created
    ON l2_projection_jobs(status, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_l2_projection_jobs_owner_status_created
    ON l2_projection_jobs(batch_owner, status, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_l2_projection_jobs_catch_up_owner_status_created
    ON l2_projection_jobs(catch_up_owner, status, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_episodes_status_time
    ON episodes(status, time_start DESC);

CREATE INDEX IF NOT EXISTS idx_episodes_parent
    ON episodes(parent_episode_id)
    WHERE parent_episode_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_episodes_type_status
    ON episodes(episode_type, status);

CREATE INDEX IF NOT EXISTS idx_episode_events_event
    ON episode_events(event_id);

CREATE INDEX IF NOT EXISTS idx_summaries_period
    ON summaries(summary_type, summary_category, period_start, period_end);

CREATE UNIQUE INDEX IF NOT EXISTS idx_summaries_insight_key
    ON summaries(insight_key) WHERE insight_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_summary_event_links_event
    ON summary_event_links(event_id);

CREATE INDEX IF NOT EXISTS idx_summary_task_links_task
    ON summary_task_links(task_id);

CREATE INDEX IF NOT EXISTS idx_l3_summary_chunks_index
    ON l3_summary_chunks(summary_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_l4_skill_chunks_index
    ON l4_skill_chunks(skill_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_l4_traces_skill
    ON l4_execution_traces(skill_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_l4_traces_turn
    ON l4_execution_traces(turn_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_entity_catalog_type ON entity_catalog(entity_type);

CREATE INDEX IF NOT EXISTS idx_entity_aliases_lookup ON entity_aliases(normalized_alias, confidence DESC);

CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity ON entity_mentions(resolved_entity_id);

CREATE INDEX IF NOT EXISTS idx_embedding_rebuild_jobs_status_updated
    ON embedding_rebuild_jobs(status, updated_at);

CREATE INDEX IF NOT EXISTS idx_embedding_rebuild_job_layers_status
    ON embedding_rebuild_job_layers(status, updated_at);

CREATE INDEX IF NOT EXISTS idx_user_profile_projection_entity
    ON user_profile_projection(entity_id);

CREATE INDEX IF NOT EXISTS idx_user_profile_projection_refreshed
    ON user_profile_projection(refreshed_at DESC);

CREATE INDEX IF NOT EXISTS idx_episodes_standout
    ON episodes(magi_standout, standout_score DESC, time_start DESC)
    WHERE magi_standout = 1 OR user_pinned = 1;

CREATE INDEX IF NOT EXISTS idx_summaries_narrative_style
    ON summaries(narrative_style, summary_type, period_start DESC);

CREATE INDEX IF NOT EXISTS idx_daily_mood_aggregate_computed
    ON daily_mood_aggregate(computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_loc_samples_time
    ON location_samples(sampled_at DESC);

CREATE INDEX IF NOT EXISTS idx_loc_samples_source_time
    ON location_samples(source, sampled_at DESC);

CREATE INDEX IF NOT EXISTS idx_manual_entries_event_at
    ON manual_entries(event_at DESC);

CREATE INDEX IF NOT EXISTS idx_manual_entries_active
    ON manual_entries(deleted_at, event_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_knowledge_graph_evidence_class
    ON knowledge_graph(evidence_class)
    WHERE evidence_class IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_tom_assertions_active_unique ON tom_trait_assertions(entity_id, entity_type, trait_name, target_entity_id) WHERE status NOT IN ('superseded', 'archived', 'expired', 'user_rejected', 'shadow');

CREATE INDEX IF NOT EXISTS idx_experiences_status_time
    ON experiences(status, time_start DESC, time_end DESC);

CREATE INDEX IF NOT EXISTS idx_experiences_parent
    ON experiences(parent_experience_id)
    WHERE parent_experience_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_experiences_merged_into
    ON experiences(merged_into_experience_id)
    WHERE merged_into_experience_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_experience_members_member
    ON experience_members(member_type, member_id);

CREATE INDEX IF NOT EXISTS idx_experience_key_events_event
    ON experience_key_events(event_id);

CREATE INDEX IF NOT EXISTS idx_experiences_source_seed
            ON experiences(source_seed_id)
            WHERE source_seed_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_experience_seeds_status_time
            ON experience_seeds(status, time_start DESC, time_end DESC);

CREATE INDEX IF NOT EXISTS idx_experience_seeds_source_ref
            ON experience_seeds(source_ref_type, source_ref_id)
            WHERE source_ref_type IS NOT NULL AND source_ref_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_experience_seed_evidence_ref
            ON experience_seed_evidence(ref_type, ref_id);

CREATE INDEX IF NOT EXISTS idx_experience_drafts_status_updated
    ON experience_drafts(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_experience_chapters_experience_position
    ON experience_chapters(experience_id, position);

CREATE INDEX IF NOT EXISTS idx_user_portrait_projection_entity
    ON user_portrait_projection(entity_id, entity_type);

CREATE INDEX IF NOT EXISTS idx_user_portrait_projection_updated
    ON user_portrait_projection(updated_at DESC);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_user_portrait_projection_updated;

DROP INDEX IF EXISTS idx_user_portrait_projection_entity;

DROP INDEX IF EXISTS idx_experience_seed_evidence_ref;

DROP INDEX IF EXISTS idx_experience_seeds_source_ref;

DROP INDEX IF EXISTS idx_experience_seeds_status_time;

DROP INDEX IF EXISTS idx_experiences_source_seed;

DROP INDEX IF EXISTS idx_experience_key_events_event;

DROP INDEX IF EXISTS idx_experience_members_member;

DROP INDEX IF EXISTS idx_experiences_merged_into;

DROP INDEX IF EXISTS idx_experiences_parent;

DROP INDEX IF EXISTS idx_experiences_status_time;

DROP INDEX IF EXISTS idx_tom_assertions_active_unique;

DROP INDEX IF EXISTS idx_knowledge_graph_evidence_class;

DROP INDEX IF EXISTS idx_manual_entries_active;

DROP INDEX IF EXISTS idx_manual_entries_event_at;

DROP INDEX IF EXISTS idx_loc_samples_source_time;

DROP INDEX IF EXISTS idx_loc_samples_time;

DROP INDEX IF EXISTS idx_daily_mood_aggregate_computed;

DROP INDEX IF EXISTS idx_summaries_narrative_style;

DROP INDEX IF EXISTS idx_episodes_standout;

DROP INDEX IF EXISTS idx_user_profile_projection_refreshed;

DROP INDEX IF EXISTS idx_user_profile_projection_entity;

DROP INDEX IF EXISTS idx_embedding_rebuild_job_layers_status;

DROP INDEX IF EXISTS idx_embedding_rebuild_jobs_status_updated;

DROP INDEX IF EXISTS idx_entity_mentions_entity;

DROP INDEX IF EXISTS idx_entity_aliases_lookup;

DROP INDEX IF EXISTS idx_entity_catalog_type;

DROP INDEX IF EXISTS idx_l4_traces_turn;

DROP INDEX IF EXISTS idx_l4_traces_skill;

DROP INDEX IF EXISTS idx_l4_skill_chunks_index;

DROP INDEX IF EXISTS idx_l3_summary_chunks_index;

DROP INDEX IF EXISTS idx_summary_task_links_task;

DROP INDEX IF EXISTS idx_summary_event_links_event;

DROP INDEX IF EXISTS idx_summaries_insight_key;

DROP INDEX IF EXISTS idx_summaries_period;

DROP INDEX IF EXISTS idx_episode_events_event;

DROP INDEX IF EXISTS idx_episodes_type_status;

DROP INDEX IF EXISTS idx_episodes_parent;

DROP INDEX IF EXISTS idx_episodes_status_time;

DROP INDEX IF EXISTS idx_l2_projection_jobs_catch_up_owner_status_created;

DROP INDEX IF EXISTS idx_l2_projection_jobs_owner_status_created;

DROP INDEX IF EXISTS idx_l2_projection_jobs_status_created;

DROP INDEX IF EXISTS idx_tom_assertions_entity_updated;

DROP INDEX IF EXISTS idx_knowledge_graph_embedding_profile;

DROP INDEX IF EXISTS idx_knowledge_graph_status_predicate;

DROP INDEX IF EXISTS idx_knowledge_graph_status_object;

DROP INDEX IF EXISTS idx_knowledge_graph_status_subject;

DROP INDEX IF EXISTS idx_entity_facets_name_value;

DROP TABLE IF EXISTS user_portrait_projection;

DROP TABLE IF EXISTS experience_seed_evidence;

DROP TABLE IF EXISTS experience_chapters;

DROP TABLE IF EXISTS experience_drafts;

DROP TABLE IF EXISTS experience_seeds;

DROP TABLE IF EXISTS experience_key_events;

DROP TABLE IF EXISTS experience_members;

DROP TABLE IF EXISTS experiences;

DROP TABLE IF EXISTS manual_entries;

DROP TABLE IF EXISTS place_labels;

DROP TABLE IF EXISTS place_geocode_cache;

DROP TABLE IF EXISTS location_samples;

DROP TABLE IF EXISTS daily_mood_aggregate;

DROP TABLE IF EXISTS user_profile_projection;

DROP TABLE IF EXISTS embedding_rebuild_job_layers;

DROP TABLE IF EXISTS embedding_rebuild_jobs;

DROP TABLE IF EXISTS episodes_fts;

DROP TABLE IF EXISTS entity_mentions;

DROP TABLE IF EXISTS entity_aliases;

DROP TABLE IF EXISTS entity_catalog;

DROP TABLE IF EXISTS l4_execution_traces;

DROP TABLE IF EXISTS l4_skills_fts;

DROP TABLE IF EXISTS l4_skill_chunks;

DROP TABLE IF EXISTS procedural_skills;

DROP TABLE IF EXISTS l3_summaries_fts;

DROP TABLE IF EXISTS l3_summary_chunks;

DROP TABLE IF EXISTS summary_task_links;

DROP TABLE IF EXISTS summary_event_links;

DROP TABLE IF EXISTS summaries;

DROP TABLE IF EXISTS episode_events;

DROP TABLE IF EXISTS episodes;

DROP TABLE IF EXISTS l2_projection_jobs;

DROP TABLE IF EXISTS graph_conflict_rules;

DROP TABLE IF EXISTS tom_snapshots;

DROP TABLE IF EXISTS tom_trait_assertions;

DROP TABLE IF EXISTS entity_facets;

DROP TABLE IF EXISTS knowledge_graph;

DROP TABLE IF EXISTS l0_execution_results;

DROP TABLE IF EXISTS l0_execution_pending_turns;

DROP TABLE IF EXISTS l0_execution_runs;

DROP TABLE IF EXISTS l0_temporary_tactics;

DROP TABLE IF EXISTS l0_active_entities;

DROP TABLE IF EXISTS l0_goal_stack;

DROP TABLE IF EXISTS l0_sessions;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
