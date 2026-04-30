use axum::extract::Query;
use axum::Json;
use serde_json::{json, Value};

use crate::db;

use super::query::{clamp_limit, clamp_offset, PaginationQuery};

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
