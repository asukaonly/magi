use axum::extract::Query;
use axum::Json;
use serde_json::{json, Value};

use crate::db;

use super::query::{clamp_limit, clamp_offset, L1EventsQuery, DEFAULT_LIMIT};

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
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    let path = db::l1_events_db_path();
    let conn = match db::open_readonly(&path) {
        Some(c) => c,
        None => return json!({"items": [], "total": 0, "limit": limit, "offset": offset}),
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
        where_parts
            .push("event_id IN (SELECT event_id FROM l1_events_fts WHERE content MATCH ?)".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }

    let where_clause = where_parts.join(" AND ");

    // Count total matching rows
    let count_sql = format!("SELECT COUNT(*) FROM fact_events WHERE {}", where_clause);
    let count_refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();
    let total = db::count_rows(&conn, &count_sql, &count_refs);

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
    let refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();

    let items = db::query_to_json_array(&conn, &sql, &refs);
    json!({"items": items, "total": total, "limit": limit, "offset": offset})
}
