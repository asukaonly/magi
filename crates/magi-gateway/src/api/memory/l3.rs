use axum::extract::Query;
use axum::Json;
use serde_json::{json, Value};

use crate::db;

use super::query::{append_like_search, clamp_limit, clamp_offset, SummariesQuery, DEFAULT_LIMIT};

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
    append_like_search(
        &mut where_parts,
        &mut bind,
        &[
            "summary_id",
            "summary_type",
            "summary_category",
            "content",
            "key_topics",
            "key_entities",
            "sentiment_summary",
            "change_and_pattern",
            "source_event_ids",
            "generated_by_model",
            "generation_prompt",
            "generation_reason",
            "insight_key",
            "review_state",
            "insight_metadata",
            "narrative_style",
            "essence_prose",
        ],
        params.query.as_deref(),
    );

    let where_clause = if where_parts.is_empty() {
        String::new()
    } else {
        format!("WHERE {} ", where_parts.join(" AND "))
    };

    // Count total matching rows
    let count_sql = format!("SELECT COUNT(*) FROM summaries {}", where_clause);
    let count_refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();
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
    let refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();

    let items = db::query_to_json_array(&conn, &sql, &refs);
    json!({"items": items, "total": total, "limit": limit, "offset": offset})
}
