use axum::extract::Query;
use axum::http::StatusCode;
use axum::Json;
use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::db;

const DEFAULT_USER_ID: &str = "default_user";
const DEFAULT_LIMIT: i64 = 30;
const MAX_LIMIT: i64 = 200;

#[derive(Deserialize)]
pub struct SessionsQuery {
    pub user_id: Option<String>,
    pub limit: Option<i64>,
}

/// Native GET /api/messages/sessions handler — reads chat.db directly.
pub async fn list_sessions(Query(params): Query<SessionsQuery>) -> (StatusCode, Json<Value>) {
    let user_id = params
        .user_id
        .unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let limit = params.limit.unwrap_or(DEFAULT_LIMIT).clamp(1, MAX_LIMIT);

    let result = tokio::task::spawn_blocking(move || query_sessions(&user_id, limit)).await;
    match result {
        Ok(Ok(value)) => (StatusCode::OK, Json(value)),
        _ => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"detail": "Conversation sessions unavailable"})),
        ),
    }
}

fn query_sessions(user_id: &str, limit: i64) -> rusqlite::Result<Value> {
    let db_path = db::chat_db_path();
    // The sidecar owns storage initialization. Missing or unreadable storage is
    // unavailable, not evidence that the user has no conversations.
    let conn = Connection::open_with_flags(&db_path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;

    let mut stmt = conn.prepare(
        "SELECT session_id, title, title_overridden, last_message_preview, \
                last_user_message_preview, workspace_path, updated_at_ms, \
                last_message_at_ms, message_count, history_version \
         FROM chat_sessions \
         WHERE user_id = ?1 \
           AND deleted_at_ms IS NULL \
           AND archived_at_ms IS NULL \
         ORDER BY updated_at_ms DESC, created_at_ms DESC \
         LIMIT ?2",
    )?;

    let rows: Vec<Value> = stmt
        .query_map(rusqlite::params![user_id, limit], |row| {
            let updated_at_ms: Option<i64> = row.get(6)?;
            let last_message_at_ms: Option<i64> = row.get(7)?;
            let last_timestamp = last_message_at_ms.or(updated_at_ms).unwrap_or(0);

            Ok(json!({
                "session_id": row.get::<_, String>(0)?,
                "title": row.get::<_, String>(1)?,
                "title_overridden": row.get::<_, bool>(2)?,
                "last_message_preview": row.get::<_, String>(3)?,
                "last_user_message_preview": row.get::<_, String>(4)?,
                "workspace_path": row.get::<_, Option<String>>(5)?,
                "last_timestamp": last_timestamp,
                "message_count": row.get::<_, i64>(8)?,
                "history_version": row.get::<_, i64>(9)?
            }))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;

    let count = rows.len();
    Ok(json!({
        "user_id": user_id,
        "sessions": rows,
        "count": count
    }))
}
