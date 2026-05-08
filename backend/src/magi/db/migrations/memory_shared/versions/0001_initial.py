"""memory_shared baseline schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-06

Materialises the canonical shared memory database (memory.db) on a
fresh runtime. The four cognitive layers (L0 working memory, L2
cognition graph, L3 summary store, L4 procedural memory) co-locate
their tables in this single file. This revision is the snapshot of
the schema as it stood the day Alembic took ownership; any further
evolution is a new revision file.
"""

from __future__ import annotations

import json
import time

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


_DEFAULT_GRAPH_CONFLICT_RULES: tuple[dict[str, object], ...] = (
    {
        "predicate": "LIKES",
        "opposite_predicates": ["DISLIKES"],
        "opposite_resolution": "mark_deprecated",
        "exclusive_group": None,
        "exclusive_scope": "same_subject",
        "exclusive_resolution": "mark_deprecated",
    },
    {
        "predicate": "DISLIKES",
        "opposite_predicates": ["LIKES"],
        "opposite_resolution": "mark_deprecated",
        "exclusive_group": None,
        "exclusive_scope": "same_subject",
        "exclusive_resolution": "mark_deprecated",
    },
    {
        "predicate": "CURRENT_WORKS_AT",
        "opposite_predicates": [],
        "opposite_resolution": "mark_deprecated",
        "exclusive_group": "current_work",
        "exclusive_scope": "same_subject",
        "exclusive_resolution": "mark_deprecated",
    },
    {
        "predicate": "CURRENT_LIVES_IN",
        "opposite_predicates": [],
        "opposite_resolution": "mark_deprecated",
        "exclusive_group": "current_residence",
        "exclusive_scope": "same_subject",
        "exclusive_resolution": "mark_deprecated",
    },
    {
        "predicate": "CURRENT_RELATIONSHIP_WITH",
        "opposite_predicates": [],
        "opposite_resolution": "mark_deprecated",
        "exclusive_group": "current_relationship",
        "exclusive_scope": "same_subject",
        "exclusive_resolution": "mark_deprecated",
    },
)


SCHEMA_SQL = """
-- ---------------------------------------------------------------------------
-- L0: working-memory checkpoints
-- ---------------------------------------------------------------------------
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
    updated_at REAL NOT NULL
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

-- ---------------------------------------------------------------------------
-- L2: cognition graph + ToM + projection jobs + episodes
-- ---------------------------------------------------------------------------
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

CREATE INDEX IF NOT EXISTS idx_l2_projection_jobs_catch_up_owner_status_created
    ON l2_projection_jobs(catch_up_owner, status, created_at ASC);

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

-- ---------------------------------------------------------------------------
-- L3: summary store
-- ---------------------------------------------------------------------------
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
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_summaries_period
    ON summaries(summary_type, summary_category, period_start, period_end);
CREATE UNIQUE INDEX IF NOT EXISTS idx_summaries_insight_key
    ON summaries(insight_key) WHERE insight_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS summary_event_links (
    link_id TEXT PRIMARY KEY,
    summary_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    link_role TEXT NOT NULL,
    evidence_weight REAL NOT NULL DEFAULT 1.0,
    created_at REAL NOT NULL,
    UNIQUE(summary_id, event_id, link_role)
);
CREATE INDEX IF NOT EXISTS idx_summary_event_links_event
    ON summary_event_links(event_id);

CREATE TABLE IF NOT EXISTS summary_task_links (
    link_id TEXT PRIMARY KEY,
    summary_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    link_role TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(summary_id, task_id, link_role)
);
CREATE INDEX IF NOT EXISTS idx_summary_task_links_task
    ON summary_task_links(task_id);

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
CREATE INDEX IF NOT EXISTS idx_l3_summary_chunks_index
    ON l3_summary_chunks(summary_id, chunk_index);

CREATE VIRTUAL TABLE IF NOT EXISTS l3_summaries_fts USING fts5(
    summary_id UNINDEXED,
    content,
    tokenize='unicode61'
);

-- ---------------------------------------------------------------------------
-- L4: procedural memory (skills + traces)
-- ---------------------------------------------------------------------------
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
CREATE INDEX IF NOT EXISTS idx_l4_skill_chunks_index
    ON l4_skill_chunks(skill_id, chunk_index);

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
CREATE INDEX IF NOT EXISTS idx_l4_traces_skill
    ON l4_execution_traces(skill_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_l4_traces_turn
    ON l4_execution_traces(turn_id, created_at ASC);

-- L2 Entity Catalog
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
CREATE INDEX IF NOT EXISTS idx_entity_catalog_type ON entity_catalog(entity_type);

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
CREATE INDEX IF NOT EXISTS idx_entity_aliases_lookup ON entity_aliases(normalized_alias, confidence DESC);

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
CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity ON entity_mentions(resolved_entity_id);

-- L2 episodes FTS5 (text search over episode label/summary)
CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    episode_id,
    summary,
    label,
    user_label
);

-- Memory embedding rebuild jobs
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
CREATE INDEX IF NOT EXISTS idx_embedding_rebuild_jobs_status_updated
    ON embedding_rebuild_jobs(status, updated_at);

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
CREATE INDEX IF NOT EXISTS idx_embedding_rebuild_job_layers_status
    ON embedding_rebuild_job_layers(status, updated_at);
"""

DROP_SQL = """
DROP TABLE IF EXISTS embedding_rebuild_job_layers;
DROP TABLE IF EXISTS embedding_rebuild_jobs;
-- L2 Entity Catalog
DROP TABLE IF EXISTS entity_mentions;
DROP TABLE IF EXISTS entity_aliases;
DROP TABLE IF EXISTS entity_catalog;
DROP TABLE IF EXISTS episodes_fts;
-- L4
DROP TABLE IF EXISTS l4_execution_traces;
DROP TABLE IF EXISTS l4_skills_fts;
DROP TABLE IF EXISTS l4_skill_chunks;
DROP TABLE IF EXISTS procedural_skills;
-- L3
DROP TABLE IF EXISTS l3_summaries_fts;
DROP TABLE IF EXISTS l3_summary_chunks;
DROP TABLE IF EXISTS summary_task_links;
DROP TABLE IF EXISTS summary_event_links;
DROP TABLE IF EXISTS summaries;
-- L2
DROP TABLE IF EXISTS episode_events;
DROP TABLE IF EXISTS episodes;
DROP TABLE IF EXISTS l2_projection_jobs;
DROP TABLE IF EXISTS graph_conflict_rules;
DROP TABLE IF EXISTS tom_snapshots;
DROP TABLE IF EXISTS tom_trait_assertions;
DROP TABLE IF EXISTS entity_facets;
DROP TABLE IF EXISTS knowledge_graph;
-- L0
DROP TABLE IF EXISTS l0_execution_results;
DROP TABLE IF EXISTS l0_execution_pending_turns;
DROP TABLE IF EXISTS l0_execution_runs;
DROP TABLE IF EXISTS l0_temporary_tactics;
DROP TABLE IF EXISTS l0_active_entities;
DROP TABLE IF EXISTS l0_goal_stack;
DROP TABLE IF EXISTS l0_sessions;
"""


def upgrade() -> None:
    bind = op.get_bind().connection
    bind.executescript(SCHEMA_SQL)

    now = time.time()
    for rule in _DEFAULT_GRAPH_CONFLICT_RULES:
        bind.execute(
            """
            INSERT OR IGNORE INTO graph_conflict_rules(
                predicate, opposite_predicates, opposite_resolution,
                exclusive_group, exclusive_scope, exclusive_resolution,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule["predicate"],
                json.dumps(rule["opposite_predicates"], ensure_ascii=False),
                rule["opposite_resolution"],
                rule["exclusive_group"],
                rule["exclusive_scope"],
                rule["exclusive_resolution"],
                now,
                now,
            ),
        )


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
