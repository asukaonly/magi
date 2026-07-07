use axum::extract::Query;
use axum::Json;
use serde_json::{json, Value};

use crate::db;

use super::query::{append_like_search, clamp_limit, clamp_offset, PaginationQuery};

// ---------------------------------------------------------------------------
// Procedures (L4)
// ---------------------------------------------------------------------------

/// GET /api/memory/procedures — skill execution procedures.
pub async fn list_procedures(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, 50);
    let offset = clamp_offset(params.offset);
    let search_query = params.query.clone();
    let result = tokio::task::spawn_blocking(move || {
        let empty = json!({"items": [], "total": 0, "limit": limit, "offset": offset});
        db::open_readonly(&db::memory_db_path())
            .map(|conn| {
                let mut where_parts: Vec<String> = Vec::new();
                let mut bind: Vec<rusqlite::types::Value> = Vec::new();
                append_like_search(
                    &mut where_parts,
                    &mut bind,
                    &[
                        "skill_id",
                        "skill_name",
                        "skill_category",
                        "skill_type",
                        "circuit_breaker_state",
                        "optimized_prompt",
                        "optimized_params",
                        "context_affinity",
                        "source_event_ids",
                    ],
                    search_query.as_deref(),
                );
                let where_clause = if where_parts.is_empty() {
                    String::new()
                } else {
                    format!("WHERE {} ", where_parts.join(" AND "))
                };
                let count_refs: Vec<&dyn rusqlite::types::ToSql> = bind
                    .iter()
                    .map(|v| v as &dyn rusqlite::types::ToSql)
                    .collect();
                let total = db::count_rows(
                    &conn,
                    &format!("SELECT COUNT(*) FROM procedural_skills {where_clause}"),
                    &count_refs,
                );
                bind.push(rusqlite::types::Value::Integer(limit));
                bind.push(rusqlite::types::Value::Integer(offset));
                let refs: Vec<&dyn rusqlite::types::ToSql> = bind
                    .iter()
                    .map(|v| v as &dyn rusqlite::types::ToSql)
                    .collect();
                let items = db::query_to_json_array(
                    &conn,
                    &format!(
                        "SELECT skill_id, skill_name, skill_category, success_rate, \
                     total_attempts, circuit_breaker_state \
                     FROM procedural_skills \
                     {where_clause} \
                     ORDER BY updated_at DESC LIMIT ? OFFSET ?"
                    ),
                    &refs,
                );
                json!({"items": items, "total": total, "limit": limit, "offset": offset})
            })
            .unwrap_or(empty)
    })
    .await
    .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset}));
    Json(result)
}
