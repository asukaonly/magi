use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::db;

use super::query::{clamp_limit, clamp_offset, PaginationQuery, DEFAULT_LIMIT};

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
        None => {
            return json!({
                "is_running": false,
                "relation_count": 0,
                "assertion_count": 0,
                "projection_backlog": {"pending": 0, "claimed": 0, "completed": 0, "failed": 0},
            })
        }
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
                    let total =
                        db::count_rows(&conn, "SELECT COUNT(*) FROM tom_trait_assertions", &[]);
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
        .filter_map(|e| {
            e.get("entity_id")
                .and_then(|v| v.as_str())
                .map(String::from)
        })
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
                let eid = obj.get("entity_id").and_then(|v| v.as_str()).unwrap_or("");
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
                    let total = db::count_rows(&conn, "SELECT COUNT(*) FROM entity_mentions", &[]);
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
                    let total = db::count_rows(&conn, "SELECT COUNT(*) FROM tom_snapshots", &[]);
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
