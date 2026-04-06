use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::db;

// ---------------------------------------------------------------------------
// Unified memory statistics
// ---------------------------------------------------------------------------

/// GET /api/memory/statistics — per-layer memory statistics (L0–L4).
pub async fn get_memory_statistics() -> Json<Value> {
    let result = tokio::task::spawn_blocking(build_memory_statistics)
        .await
        .unwrap_or_else(|_| json!({}));
    Json(result)
}

fn build_memory_statistics() -> Value {
    let mut stats = json!({});

    // L0 — from memory.db checkpoint tables
    if let Some(conn) = db::open_readonly(&db::memory_db_path()) {
        let active_sessions = db::count_rows(
            &conn,
            "SELECT COUNT(*) FROM l0_sessions WHERE status = 'active'",
            &[],
        );
        let total_goals = db::count_rows(&conn, "SELECT COUNT(*) FROM l0_goal_stack", &[]);
        let total_entities = db::count_rows(&conn, "SELECT COUNT(*) FROM l0_active_entities", &[]);
        let total_tactics = db::count_rows(&conn, "SELECT COUNT(*) FROM l0_temporary_tactics", &[]);
        stats["l0"] = json!({
            "active_sessions": active_sessions,
            "total_goals": total_goals,
            "total_entities": total_entities,
            "total_tactics": total_tactics,
        });

        // L2
        let rel_count = db::count_rows(
            &conn,
            "SELECT COUNT(*) FROM knowledge_graph WHERE status = 'active'",
            &[],
        );
        let tom_count = db::count_rows(&conn, "SELECT COUNT(*) FROM tom_trait_assertions", &[]);
        stats["l2"] = json!({
            "relation_count": rel_count,
            "assertion_count": tom_count,
        });

        // L3
        let summary_count = db::count_rows(&conn, "SELECT COUNT(*) FROM summaries", &[]);
        stats["l3"] = json!({ "summary_count": summary_count });

        // L4
        let skill_count = db::count_rows(&conn, "SELECT COUNT(*) FROM procedural_skills", &[]);
        stats["l4"] = json!({ "skill_count": skill_count, "open_circuit_breakers": 0 });
    }

    // L1 — from l1_events.db
    if let Some(conn) = db::open_readonly(&db::l1_events_db_path()) {
        let event_count = db::count_rows(
            &conn,
            "SELECT COUNT(*) FROM fact_events WHERE deleted_at IS NULL",
            &[],
        );
        stats["l1"] = json!({ "event_count": event_count });
    }

    stats
}

// ---------------------------------------------------------------------------
// L2 cognition statistics
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/statistics — L2 pipeline statistics.
pub async fn get_l2_statistics() -> Json<Value> {
    let result = tokio::task::spawn_blocking(build_l2_statistics)
        .await
        .unwrap_or_else(|_| json!({}));
    Json(result)
}

fn build_l2_statistics() -> Value {
    let conn = match db::open_readonly(&db::memory_db_path()) {
        Some(c) => c,
        None => return json!({
            "is_running": false,
            "relation_count": 0,
            "assertion_count": 0,
            "projection_backlog": {"pending": 0, "claimed": 0, "completed": 0, "failed": 0},
        }),
    };

    let rel_count = db::count_rows(
        &conn,
        "SELECT COUNT(*) FROM knowledge_graph WHERE status = 'active'",
        &[],
    );
    let tom_count = db::count_rows(&conn, "SELECT COUNT(*) FROM tom_trait_assertions", &[]);

    // Projection backlog by status
    let backlog_rows = db::query_to_json_array(
        &conn,
        "SELECT status, COUNT(*) AS cnt FROM l2_projection_jobs GROUP BY status",
        &[],
    );
    let mut pending: i64 = 0;
    let mut claimed: i64 = 0;
    let mut completed: i64 = 0;
    let mut failed: i64 = 0;
    for row in &backlog_rows {
        let s = row.get("status").and_then(|v| v.as_str()).unwrap_or("");
        let n = row.get("cnt").and_then(|v| v.as_i64()).unwrap_or(0);
        match s {
            "pending" => pending = n,
            "claimed" => claimed = n,
            "completed" => completed = n,
            "failed" => failed = n,
            _ => {}
        }
    }

    json!({
        "is_running": false,
        "relation_count": rel_count,
        "assertion_count": tom_count,
        "extract_enqueued": 0,
        "extract_completed": 0,
        "extract_failed": 0,
        "extract_skipped": 0,
        "reconcile_enqueued": 0,
        "reconcile_completed": 0,
        "reconcile_failed": 0,
        "snapshot_enqueued": 0,
        "snapshot_completed": 0,
        "snapshot_failed": 0,
        "relations_written": 0,
        "assertions_written": 0,
        "extract_by_evidence_class": {},
        "skip_by_reason": {},
        "projection_backlog": {
            "pending": pending,
            "claimed": claimed,
            "completed": completed,
            "failed": failed,
        },
    })
}

// ---------------------------------------------------------------------------
// Identity links
// ---------------------------------------------------------------------------

/// GET /api/memory/identity/links — identity mappings.
pub async fn get_identity_links() -> Json<Value> {
    Json(json!({
        "canonical_self_id": "user:self",
        "links": [],
    }))
}

const DEFAULT_LIMIT: i64 = 100;
const MAX_LIMIT: i64 = 500;

fn clamp_limit(limit: Option<i64>, default: i64) -> i64 {
    limit.unwrap_or(default).clamp(1, MAX_LIMIT)
}

// ---------------------------------------------------------------------------
// Query parameter structs
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct L1EventsQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
    pub event_type: Option<String>,
    pub user_id: Option<String>,
    pub session_id: Option<String>,
    pub query: Option<String>,
    pub source: Option<String>,
    pub source_item_id: Option<String>,
    pub idempotency_key: Option<String>,
    pub start_date: Option<String>,
    pub end_date: Option<String>,
}

#[derive(Deserialize)]
pub struct PaginationQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

#[derive(Deserialize)]
pub struct SummariesQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
    pub summary_type: Option<String>,
    pub summary_category: Option<String>,
}

fn clamp_offset(offset: Option<i64>) -> i64 {
    offset.unwrap_or(0).max(0)
}

// ---------------------------------------------------------------------------
// L1 Events
// ---------------------------------------------------------------------------

/// GET /api/memory/l1/events — query fact_events from l1_events.db.
pub async fn list_l1_events(Query(params): Query<L1EventsQuery>) -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || build_l1_events_response(&params))
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": 50, "offset": 0}));
    Json(result)
}

fn build_l1_events_response(params: &L1EventsQuery) -> Value {
    let path = db::l1_events_db_path();
    let conn = match db::open_readonly(&path) {
        Some(c) => c,
        None => return json!({"items": [], "total": 0, "limit": 50, "offset": 0}),
    };

    let mut where_parts = vec!["deleted_at IS NULL".to_string()];
    let mut bind: Vec<rusqlite::types::Value> = Vec::new();

    if let Some(ref v) = params.event_type {
        where_parts.push("event_type = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.user_id {
        where_parts.push("user_id = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.session_id {
        where_parts.push("session_id = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.source {
        where_parts.push("source = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.source_item_id {
        where_parts.push("source_item_id = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.idempotency_key {
        where_parts.push("idempotency_key = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.start_date {
        if let Ok(ts) = v.parse::<f64>() {
            where_parts.push("timestamp >= ?".into());
            bind.push(rusqlite::types::Value::Real(ts));
        }
    }
    if let Some(ref v) = params.end_date {
        if let Ok(ts) = v.parse::<f64>() {
            where_parts.push("timestamp <= ?".into());
            bind.push(rusqlite::types::Value::Real(ts));
        }
    }
    if let Some(ref v) = params.query {
        where_parts.push(
            "event_id IN (SELECT event_id FROM l1_events_fts WHERE content MATCH ?)".into(),
        );
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }

    let where_clause = where_parts.join(" AND ");

    // Count total matching rows
    let count_sql = format!("SELECT COUNT(*) FROM fact_events WHERE {}", where_clause);
    let count_refs: Vec<&dyn rusqlite::types::ToSql> =
        bind.iter().map(|v| v as &dyn rusqlite::types::ToSql).collect();
    let total = db::count_rows(&conn, &count_sql, &count_refs);

    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    bind.push(rusqlite::types::Value::Integer(limit));
    bind.push(rusqlite::types::Value::Integer(offset));

    // Exclude embedding/metadata columns not needed by the list view.
    let sql = format!(
        "SELECT id, event_id, correlation_id, timestamp, created_at, event_type, \
         source, source_item_id, idempotency_key, memory_domain, ingest_target, \
         cognition_eligible, tom_depth, retention_class, session_id, turn_id, \
         user_id, task_id, content, author_type, content_type, importance_score, \
         level, media_path, deleted_at \
         FROM fact_events WHERE {} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        where_clause
    );
    let refs: Vec<&dyn rusqlite::types::ToSql> =
        bind.iter().map(|v| v as &dyn rusqlite::types::ToSql).collect();

    let items = db::query_to_json_array(&conn, &sql, &refs);
    json!({"items": items, "total": total, "limit": limit, "offset": offset})
}

// ---------------------------------------------------------------------------
// L2 Relations
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/relations — active knowledge graph triples.
pub async fn list_l2_relations(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    Json(
        tokio::task::spawn_blocking(move || {
            let empty = json!({"items": [], "total": 0, "limit": limit, "offset": offset});
            db::open_readonly(&db::memory_db_path())
                .map(|conn| {
                    let total = db::count_rows(
                        &conn,
                        "SELECT COUNT(*) FROM knowledge_graph WHERE status = 'active'",
                        &[],
                    );
                    let items = db::query_to_json_array(
                        &conn,
                        "SELECT * FROM knowledge_graph \
                         WHERE status = 'active' \
                         ORDER BY updated_at DESC LIMIT ?1 OFFSET ?2",
                        rusqlite::params![limit, offset],
                    );
                    json!({"items": items, "total": total, "limit": limit, "offset": offset})
                })
                .unwrap_or(empty)
        })
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset})),
    )
}

// ---------------------------------------------------------------------------
// L2 Assertions
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/assertions — ToM trait assertions.
pub async fn list_l2_assertions(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    Json(
        tokio::task::spawn_blocking(move || {
            let empty = json!({"items": [], "total": 0, "limit": limit, "offset": offset});
            db::open_readonly(&db::memory_db_path())
                .map(|conn| {
                    let total = db::count_rows(
                        &conn,
                        "SELECT COUNT(*) FROM tom_trait_assertions",
                        &[],
                    );
                    let items = db::query_to_json_array(
                        &conn,
                        "SELECT * FROM tom_trait_assertions \
                         ORDER BY updated_at DESC LIMIT ?1 OFFSET ?2",
                        rusqlite::params![limit, offset],
                    );
                    json!({"items": items, "total": total, "limit": limit, "offset": offset})
                })
                .unwrap_or(empty)
        })
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset})),
    )
}

// ---------------------------------------------------------------------------
// L2 Entities (with aliases join)
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/entities — entity catalog with aliases.
pub async fn list_l2_entities(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    let result = tokio::task::spawn_blocking(move || build_l2_entities(limit, offset))
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset}));
    Json(result)
}

fn build_l2_entities(limit: i64, offset: i64) -> Value {
    let conn = match db::open_readonly(&db::memory_db_path()) {
        Some(c) => c,
        None => return json!({"items": [], "total": 0, "limit": limit, "offset": offset}),
    };

    let total = db::count_rows(&conn, "SELECT COUNT(*) FROM entity_catalog", &[]);

    let entities = db::query_to_json_array(
        &conn,
        "SELECT entity_id, canonical_name, entity_type, embedding_status, last_embedded_at \
         FROM entity_catalog ORDER BY entity_id ASC LIMIT ?1 OFFSET ?2",
        rusqlite::params![limit, offset],
    );

    // Collect entity_ids from the current page to scope the alias query.
    let entity_ids: Vec<String> = entities
        .iter()
        .filter_map(|e| e.get("entity_id").and_then(|v| v.as_str()).map(String::from))
        .collect();

    let mut alias_map: HashMap<String, Vec<String>> = HashMap::new();
    if !entity_ids.is_empty() {
        let placeholders: String = entity_ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let alias_sql = format!(
            "SELECT entity_id, alias_text FROM entity_aliases \
             WHERE entity_id IN ({}) ORDER BY normalized_alias ASC",
            placeholders
        );
        let bind_values: Vec<rusqlite::types::Value> = entity_ids
            .iter()
            .map(|id| rusqlite::types::Value::Text(id.clone()))
            .collect();
        let refs: Vec<&dyn rusqlite::types::ToSql> = bind_values
            .iter()
            .map(|v| v as &dyn rusqlite::types::ToSql)
            .collect();
        let alias_rows = db::query_to_json_array(&conn, &alias_sql, &refs);
        for row in &alias_rows {
            if let (Some(eid), Some(text)) = (
                row.get("entity_id").and_then(|v| v.as_str()),
                row.get("alias_text").and_then(|v| v.as_str()),
            ) {
                alias_map
                    .entry(eid.to_string())
                    .or_default()
                    .push(text.to_string());
            }
        }
    }

    let items: Vec<Value> = entities
        .into_iter()
        .map(|mut e| {
            if let Some(obj) = e.as_object_mut() {
                let eid = obj
                    .get("entity_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let aliases = alias_map.remove(eid).unwrap_or_default();
                obj.insert("aliases".to_string(), json!(aliases));
            }
            e
        })
        .collect();

    json!({"items": items, "total": total, "limit": limit, "offset": offset})
}

// ---------------------------------------------------------------------------
// L2 Mentions
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/mentions — entity mentions.
pub async fn list_l2_mentions(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    Json(
        tokio::task::spawn_blocking(move || {
            let empty = json!({"items": [], "total": 0, "limit": limit, "offset": offset});
            db::open_readonly(&db::memory_db_path())
                .map(|conn| {
                    let total = db::count_rows(
                        &conn,
                        "SELECT COUNT(*) FROM entity_mentions",
                        &[],
                    );
                    let items = db::query_to_json_array(
                        &conn,
                        "SELECT * FROM entity_mentions \
                         ORDER BY mention_id DESC LIMIT ?1 OFFSET ?2",
                        rusqlite::params![limit, offset],
                    );
                    json!({"items": items, "total": total, "limit": limit, "offset": offset})
                })
                .unwrap_or(empty)
        })
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset})),
    )
}

// ---------------------------------------------------------------------------
// L2 Snapshots
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/snapshots — ToM entity snapshots.
pub async fn list_l2_snapshots(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    Json(
        tokio::task::spawn_blocking(move || {
            let empty = json!({"items": [], "total": 0, "limit": limit, "offset": offset});
            db::open_readonly(&db::memory_db_path())
                .map(|conn| {
                    let total = db::count_rows(
                        &conn,
                        "SELECT COUNT(*) FROM tom_snapshots",
                        &[],
                    );
                    // Only select columns the frontend uses; skip heavy
                    // history/evolution columns (relationship_history etc.).
                    let items = db::query_to_json_array(
                        &conn,
                        "SELECT snapshot_id, entity_id, entity_type, \
                         core_traits, preferences, relationship_topology, \
                         current_stress_level, current_mood, current_engagement, \
                         current_context, interaction_count, last_interaction_at, \
                         last_updated_at, snapshot_version, created_at, \
                         sensitive_triggers, public_sentiment_profile, \
                         update_source_assertion_ids \
                         FROM tom_snapshots \
                         ORDER BY last_updated_at DESC LIMIT ?1 OFFSET ?2",
                        rusqlite::params![limit, offset],
                    );
                    json!({"items": items, "total": total, "limit": limit, "offset": offset})
                })
                .unwrap_or(empty)
        })
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset})),
    )
}

// ---------------------------------------------------------------------------
// L2 Conflict Rules
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/conflict-rules — graph conflict resolution rules.
pub async fn list_l2_conflict_rules() -> Json<Value> {
    Json(
        tokio::task::spawn_blocking(move || {
            db::open_readonly(&db::memory_db_path())
                .map(|conn| {
                    json!(db::query_to_json_array(
                        &conn,
                        "SELECT * FROM graph_conflict_rules ORDER BY predicate ASC",
                        rusqlite::params![],
                    ))
                })
                .unwrap_or_else(|| json!([]))
        })
        .await
        .unwrap_or_else(|_| json!([])),
    )
}

// ---------------------------------------------------------------------------
// L3 Summaries
// ---------------------------------------------------------------------------

/// GET /api/memory/l3/summaries — reflection summaries with optional filters.
pub async fn list_l3_summaries(Query(params): Query<SummariesQuery>) -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || build_l3_summaries(&params))
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": 50, "offset": 0}));
    Json(result)
}

fn build_l3_summaries(params: &SummariesQuery) -> Value {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    let conn = match db::open_readonly(&db::memory_db_path()) {
        Some(c) => c,
        None => return json!({"items": [], "total": 0, "limit": limit, "offset": offset}),
    };

    let mut where_parts: Vec<String> = Vec::new();
    let mut bind: Vec<rusqlite::types::Value> = Vec::new();

    if let Some(ref v) = params.summary_type {
        where_parts.push("summary_type = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.summary_category {
        where_parts.push("summary_category = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }

    let where_clause = if where_parts.is_empty() {
        String::new()
    } else {
        format!("WHERE {} ", where_parts.join(" AND "))
    };

    // Count total matching rows
    let count_sql = format!("SELECT COUNT(*) FROM summaries {}", where_clause);
    let count_refs: Vec<&dyn rusqlite::types::ToSql> =
        bind.iter().map(|v| v as &dyn rusqlite::types::ToSql).collect();
    let total = db::count_rows(&conn, &count_sql, &count_refs);

    bind.push(rusqlite::types::Value::Integer(limit));
    bind.push(rusqlite::types::Value::Integer(offset));

    let sql = format!(
        "SELECT summary_id, summary_type, summary_category, \
         period_start, period_end, content, key_topics, key_entities, \
         sentiment_summary, change_and_pattern, source_event_count, \
         importance_aggregate, created_at, updated_at \
         FROM summaries {}ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        where_clause
    );
    let refs: Vec<&dyn rusqlite::types::ToSql> =
        bind.iter().map(|v| v as &dyn rusqlite::types::ToSql).collect();

    let items = db::query_to_json_array(&conn, &sql, &refs);
    json!({"items": items, "total": total, "limit": limit, "offset": offset})
}

// ---------------------------------------------------------------------------
// L0 Sessions (from checkpoint tables)
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct L0SessionsQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
    pub status: Option<String>,
    pub query: Option<String>,
}

/// GET /api/memory/l0/sessions — paginated session list with counts.
pub async fn list_l0_sessions(Query(params): Query<L0SessionsQuery>) -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || build_l0_sessions(&params))
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": 50, "offset": 0, "stats": {}}));
    Json(result)
}

fn build_l0_sessions(params: &L0SessionsQuery) -> Value {
    let limit = clamp_limit(params.limit, 50);
    let offset = clamp_offset(params.offset);

    let mem_conn = match db::open_readonly(&db::memory_db_path()) {
        Some(c) => c,
        None => {
            return json!({
                "items": [], "total": 0, "limit": limit, "offset": offset,
                "stats": {"active_sessions": 0, "total_goals": 0, "total_entities": 0, "total_tactics": 0}
            })
        }
    };

    // Build WHERE clause
    let mut where_parts = Vec::new();
    let mut bind: Vec<rusqlite::types::Value> = Vec::new();
    if let Some(ref s) = params.status {
        where_parts.push("s.status = ?".to_string());
        bind.push(rusqlite::types::Value::Text(s.clone()));
    }
    if let Some(ref q) = params.query {
        where_parts.push("s.session_id LIKE ?".to_string());
        bind.push(rusqlite::types::Value::Text(format!("%{}%", q)));
    }

    let where_clause = if where_parts.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", where_parts.join(" AND "))
    };

    let count_sql = format!("SELECT COUNT(*) FROM l0_sessions s {}", where_clause);
    let count_refs: Vec<&dyn rusqlite::types::ToSql> =
        bind.iter().map(|v| v as &dyn rusqlite::types::ToSql).collect();
    let total = db::count_rows(&mem_conn, &count_sql, &count_refs);

    bind.push(rusqlite::types::Value::Integer(limit));
    bind.push(rusqlite::types::Value::Integer(offset));

    // Query sessions with sub-select counts
    let sql = format!(
        "SELECT s.session_id, s.user_id, s.status, s.started_at, s.last_active_at, \
         (SELECT COUNT(*) FROM l0_goal_stack g WHERE g.session_id = s.session_id) AS goal_count, \
         (SELECT COUNT(*) FROM l0_active_entities e WHERE e.session_id = s.session_id) AS entity_count, \
         (SELECT COUNT(*) FROM l0_temporary_tactics t WHERE t.session_id = s.session_id) AS tactic_count \
         FROM l0_sessions s {} \
         ORDER BY s.last_active_at DESC LIMIT ? OFFSET ?",
        where_clause
    );
    let refs: Vec<&dyn rusqlite::types::ToSql> =
        bind.iter().map(|v| v as &dyn rusqlite::types::ToSql).collect();
    let sessions = db::query_to_json_array(&mem_conn, &sql, &refs);

    // Collect session_ids to batch-lookup chat titles
    let session_ids: Vec<String> = sessions
        .iter()
        .filter_map(|s| s.get("session_id").and_then(|v| v.as_str()).map(String::from))
        .collect();

    let title_map = build_chat_title_map(&session_ids);

    let mut items = Vec::with_capacity(sessions.len());
    let mut total_goals: i64 = 0;
    let mut total_entities: i64 = 0;
    let mut total_tactics: i64 = 0;
    let mut active_sessions: i64 = 0;

    for s in &sessions {
        let sid = s.get("session_id").and_then(|v| v.as_str()).unwrap_or("");
        let gc = s.get("goal_count").and_then(|v| v.as_i64()).unwrap_or(0);
        let ec = s.get("entity_count").and_then(|v| v.as_i64()).unwrap_or(0);
        let tc = s.get("tactic_count").and_then(|v| v.as_i64()).unwrap_or(0);
        total_goals += gc;
        total_entities += ec;
        total_tactics += tc;

        if s.get("status").and_then(|v| v.as_str()) == Some("active") {
            active_sessions += 1;
        }

        let short_id = short_session_id(sid);
        let chat_title = title_map.get(sid).cloned().unwrap_or_default();
        let display_title = if !chat_title.is_empty() && !is_generic_chat_title(&chat_title) {
            chat_title
        } else {
            short_id.clone()
        };

        let mut item = s.clone();
        if let Some(obj) = item.as_object_mut() {
            obj.insert("short_session_id".into(), json!(short_id));
            obj.insert("display_title".into(), json!(display_title));
            obj.insert("display_subtitle".into(), Value::Null);
        }
        items.push(item);
    }

    json!({
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "stats": {
            "active_sessions": active_sessions,
            "total_goals": total_goals,
            "total_entities": total_entities,
            "total_tactics": total_tactics,
        }
    })
}

/// Batch-fetch chat session titles from chat.db.
fn build_chat_title_map(session_ids: &[String]) -> HashMap<String, String> {
    let mut map = HashMap::new();
    if session_ids.is_empty() {
        return map;
    }
    let conn = match db::open_readonly(&db::chat_db_path()) {
        Some(c) => c,
        None => return map,
    };
    let placeholders: String = session_ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
    let sql = format!(
        "SELECT session_id, title FROM chat_sessions WHERE session_id IN ({})",
        placeholders
    );
    let bind_vals: Vec<rusqlite::types::Value> = session_ids
        .iter()
        .map(|id| rusqlite::types::Value::Text(id.clone()))
        .collect();
    let refs: Vec<&dyn rusqlite::types::ToSql> = bind_vals
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();
    let rows = db::query_to_json_array(&conn, &sql, &refs);
    for row in &rows {
        if let (Some(sid), Some(title)) = (
            row.get("session_id").and_then(|v| v.as_str()),
            row.get("title").and_then(|v| v.as_str()),
        ) {
            map.insert(sid.to_string(), title.to_string());
        }
    }
    map
}

fn short_session_id(id: &str) -> String {
    if id.len() > 12 {
        id[..12].to_string()
    } else {
        id.to_string()
    }
}

fn is_generic_chat_title(title: &str) -> bool {
    let t = title.trim().to_lowercase();
    t.is_empty() || t == "new chat" || t == "新对话"
}

// ---------------------------------------------------------------------------
// L0 Workbench
// ---------------------------------------------------------------------------

/// GET /api/memory/l0/workbench/{session_id} — goals, entities, tactics.
pub async fn get_l0_workbench(Path(session_id): Path<String>) -> Result<Json<Value>, StatusCode> {
    let result = tokio::task::spawn_blocking(move || build_l0_workbench(&session_id))
        .await
        .unwrap_or(None);
    match result {
        Some(v) => Ok(Json(v)),
        None => Err(StatusCode::NOT_FOUND),
    }
}

fn build_l0_workbench(session_id: &str) -> Option<Value> {
    let conn = db::open_readonly(&db::memory_db_path())?;

    // Verify session exists
    let session_rows = db::query_to_json_array(
        &conn,
        "SELECT * FROM l0_sessions WHERE session_id = ?1",
        rusqlite::params![session_id],
    );
    let session = session_rows.into_iter().next()?;

    let goals = db::query_to_json_array(
        &conn,
        "SELECT * FROM l0_goal_stack WHERE session_id = ?1 ORDER BY stack_id ASC",
        rusqlite::params![session_id],
    );
    let entities = db::query_to_json_array(
        &conn,
        "SELECT * FROM l0_active_entities WHERE session_id = ?1 ORDER BY last_accessed_at DESC",
        rusqlite::params![session_id],
    );
    let tactics = db::query_to_json_array(
        &conn,
        "SELECT * FROM l0_temporary_tactics WHERE session_id = ?1 ORDER BY created_at DESC",
        rusqlite::params![session_id],
    );

    Some(json!({
        "session": session,
        "goals": goals,
        "entities": entities,
        "tactics": tactics,
    }))
}

// ---------------------------------------------------------------------------
// L2 Pending
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/pending — queue backlog stats.
pub async fn get_l2_pending() -> Json<Value> {
    let result = tokio::task::spawn_blocking(build_l2_pending)
        .await
        .unwrap_or_else(|_| json!({}));
    Json(result)
}

fn build_l2_pending() -> Value {
    let (pending, claimed, failed) = match db::open_readonly(&db::memory_db_path()) {
        Some(conn) => {
            let rows = db::query_to_json_array(
                &conn,
                "SELECT status, COUNT(*) AS cnt FROM l2_projection_jobs GROUP BY status",
                &[],
            );
            let mut p: i64 = 0;
            let mut c: i64 = 0;
            let mut f: i64 = 0;
            for row in &rows {
                let s = row.get("status").and_then(|v| v.as_str()).unwrap_or("");
                let n = row.get("cnt").and_then(|v| v.as_i64()).unwrap_or(0);
                match s {
                    "pending" => p = n,
                    "claimed" => c = n,
                    "failed" => f = n,
                    _ => {}
                }
            }
            (p, c, f)
        }
        None => (0, 0, 0),
    };

    json!({
        "is_running": false,
        "extract_pending": pending + claimed,
        "reconcile_pending": 0,
        "snapshot_pending": 0,
        "projection_pending": pending,
        "projection_claimed": claimed,
        "projection_failed": failed,
    })
}

// ---------------------------------------------------------------------------
// Background Pending
// ---------------------------------------------------------------------------

/// GET /api/memory/background/pending — multi-layer pending counts.
pub async fn get_background_pending() -> Json<Value> {
    let result = tokio::task::spawn_blocking(build_background_pending)
        .await
        .unwrap_or_else(|_| json!({}));
    Json(result)
}

fn build_background_pending() -> Value {
    let l2 = build_l2_pending();

    // Embedding pending counts read from the DB.
    let l1_pending = build_embedding_pending_from_db(&db::l1_events_db_path(), "fact_events");
    let l3_pending = build_embedding_pending_from_db(&db::memory_db_path(), "summaries");
    let l4_pending = build_embedding_pending_from_db(&db::memory_db_path(), "procedural_skills");

    let all_idle = l2.get("extract_pending").and_then(|v| v.as_i64()).unwrap_or(0) == 0
        && l2.get("reconcile_pending").and_then(|v| v.as_i64()).unwrap_or(0) == 0
        && l2.get("snapshot_pending").and_then(|v| v.as_i64()).unwrap_or(0) == 0
        && l1_pending.get("pending").and_then(|v| v.as_i64()).unwrap_or(0) == 0
        && l3_pending.get("pending").and_then(|v| v.as_i64()).unwrap_or(0) == 0
        && l4_pending.get("pending").and_then(|v| v.as_i64()).unwrap_or(0) == 0;

    json!({
        "l2": l2,
        "l1_embeddings": l1_pending,
        "l3_embeddings": l3_pending,
        "l4_embeddings": l4_pending,
        "all_idle": all_idle,
    })
}

/// Count rows with embedding_status = 'pending' in a given table.
fn build_embedding_pending_from_db(db_path: &std::path::Path, table: &str) -> Value {
    if let Some(conn) = db::open_readonly(db_path) {
        let sql = format!(
            "SELECT COUNT(*) FROM {} WHERE embedding_status = 'pending'",
            table
        );
        let pending = db::count_rows(&conn, &sql, &[]);
        return json!({
            "pending": pending,
            "worker_running": false,
            "vector_enabled": false,
            "async_embeddings": false,
        });
    }
    json!({"pending": 0, "worker_running": false, "vector_enabled": false, "async_embeddings": false})
}

// ---------------------------------------------------------------------------
// Procedures (L4)
// ---------------------------------------------------------------------------

/// GET /api/memory/procedures — skill execution procedures.
pub async fn list_procedures(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, 50);
    let offset = clamp_offset(params.offset);
    let result = tokio::task::spawn_blocking(move || {
        let empty = json!({"items": [], "total": 0, "limit": limit, "offset": offset});
        db::open_readonly(&db::memory_db_path())
            .map(|conn| {
                let total = db::count_rows(&conn, "SELECT COUNT(*) FROM procedural_skills", &[]);
                let items = db::query_to_json_array(
                    &conn,
                    "SELECT skill_id, skill_name, skill_category, success_rate, \
                     total_attempts, circuit_breaker_state \
                     FROM procedural_skills \
                     ORDER BY updated_at DESC LIMIT ?1 OFFSET ?2",
                    rusqlite::params![limit, offset],
                );
                json!({"items": items, "total": total, "limit": limit, "offset": offset})
            })
            .unwrap_or(empty)
    })
    .await
    .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset}));
    Json(result)
}

// ---------------------------------------------------------------------------
// ToM Snapshot (single entity)
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct TomQuery {
    pub entity_type: Option<String>,
}

/// GET /api/memory/tom/{entity_id} — ToM snapshot for an entity.
pub async fn get_tom_snapshot(
    Path(entity_id): Path<String>,
    Query(params): Query<TomQuery>,
) -> Result<Json<Value>, StatusCode> {
    let result = tokio::task::spawn_blocking(move || {
        let entity_type = params.entity_type.as_deref().unwrap_or("user");
        let conn = db::open_readonly(&db::memory_db_path())?;
        let rows = db::query_to_json_array(
            &conn,
            "SELECT * FROM tom_snapshots WHERE entity_id = ?1 AND entity_type = ?2",
            rusqlite::params![entity_id, entity_type],
        );
        rows.into_iter().next()
    })
    .await
    .unwrap_or(None);
    match result {
        Some(v) => Ok(Json(v)),
        None => Err(StatusCode::NOT_FOUND),
    }
}
