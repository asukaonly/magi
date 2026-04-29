use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::db;

use super::query::{clamp_limit, clamp_offset};

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
        .unwrap_or_else(
            |_| json!({"items": [], "total": 0, "limit": 50, "offset": 0, "stats": {}}),
        );
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
    let count_refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();
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
    let refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();
    let sessions = db::query_to_json_array(&mem_conn, &sql, &refs);

    // Collect session_ids to batch-lookup chat titles
    let session_ids: Vec<String> = sessions
        .iter()
        .filter_map(|s| {
            s.get("session_id")
                .and_then(|v| v.as_str())
                .map(String::from)
        })
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
    let placeholders: String = session_ids
        .iter()
        .map(|_| "?")
        .collect::<Vec<_>>()
        .join(",");
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
