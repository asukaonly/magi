use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::db;

use super::query::{clamp_limit, clamp_offset};

#[derive(Clone, Default)]
struct ChatSessionSummary {
    title: String,
    last_message_preview: String,
    last_user_message_preview: String,
    workspace_path: Option<String>,
    message_count: i64,
    title_overridden: bool,
    history_version: i64,
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

    let summary_map = build_chat_summary_map(&session_ids);

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
        let summary = summary_map.get(sid).cloned().unwrap_or_default();
        let (display_title, display_subtitle) = derive_session_display(sid, &short_id, &summary);

        let mut item = s.clone();
        if let Some(obj) = item.as_object_mut() {
            obj.insert("short_session_id".into(), json!(short_id));
            obj.insert("display_title".into(), json!(display_title));
            obj.insert(
                "display_subtitle".into(),
                display_subtitle.map(Value::String).unwrap_or(Value::Null),
            );
            obj.insert(
                "workspace_path".into(),
                summary
                    .workspace_path
                    .map(Value::String)
                    .unwrap_or(Value::Null),
            );
            obj.insert("message_count".into(), json!(summary.message_count));
            obj.insert(
                "last_message_preview".into(),
                json!(summary.last_message_preview),
            );
            obj.insert(
                "last_user_message_preview".into(),
                json!(summary.last_user_message_preview),
            );
            obj.insert("title_overridden".into(), json!(summary.title_overridden));
            obj.insert("history_version".into(), json!(summary.history_version));
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

fn build_chat_summary_map(session_ids: &[String]) -> HashMap<String, ChatSessionSummary> {
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
        "SELECT session_id, title, last_message_preview, last_user_message_preview, workspace_path, message_count, title_overridden, history_version FROM chat_sessions WHERE session_id IN ({})",
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
        if let Some(sid) = row.get("session_id").and_then(|v| v.as_str()) {
            map.insert(
                sid.to_string(),
                ChatSessionSummary {
                    title: row
                        .get("title")
                        .and_then(|v| v.as_str())
                        .unwrap_or_default()
                        .to_string(),
                    last_message_preview: row
                        .get("last_message_preview")
                        .and_then(|v| v.as_str())
                        .unwrap_or_default()
                        .to_string(),
                    last_user_message_preview: row
                        .get("last_user_message_preview")
                        .and_then(|v| v.as_str())
                        .unwrap_or_default()
                        .to_string(),
                    workspace_path: row
                        .get("workspace_path")
                        .and_then(|v| v.as_str())
                        .map(str::to_string),
                    message_count: row
                        .get("message_count")
                        .and_then(|v| v.as_i64())
                        .unwrap_or(0),
                    title_overridden: row
                        .get("title_overridden")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false),
                    history_version: row
                        .get("history_version")
                        .and_then(|v| v.as_i64())
                        .unwrap_or(0),
                },
            );
        }
    }
    map
}

fn truncate_session_preview(value: &str, limit: usize) -> String {
    let normalized = value.split_whitespace().collect::<Vec<_>>().join(" ");
    if normalized.chars().count() <= limit {
        return normalized;
    }
    normalized
        .chars()
        .take(limit.saturating_sub(1))
        .collect::<String>()
        .trim_end()
        .to_string()
        + "..."
}

fn derive_session_display(
    session_id: &str,
    short_id: &str,
    summary: &ChatSessionSummary,
) -> (String, Option<String>) {
    let chat_title = truncate_session_preview(&summary.title, 72);
    let user_preview = truncate_session_preview(&summary.last_user_message_preview, 72);
    let last_preview = truncate_session_preview(&summary.last_message_preview, 72);
    let workspace_name = summary
        .workspace_path
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .and_then(|value| value.rsplit('/').next())
        .map(str::to_string)
        .unwrap_or_default();

    let display_title = if !chat_title.is_empty() && !is_generic_chat_title(&chat_title) {
        chat_title
    } else if !user_preview.is_empty() {
        user_preview.clone()
    } else if !last_preview.is_empty() {
        last_preview.clone()
    } else if !short_id.is_empty() {
        short_id.to_string()
    } else {
        session_id.to_string()
    };

    let display_subtitle = [user_preview, last_preview, workspace_name]
        .into_iter()
        .find(|candidate| !candidate.is_empty() && candidate != &display_title);

    (display_title, display_subtitle)
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
    t.is_empty() || t == "new chat" || t == "new session" || t == "新对话" || t == "新会话"
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
    let active_context_summary = build_active_context_summary(session_id);
    let context_usage = build_latest_context_usage(session_id);

    Some(json!({
        "session": session,
        "goal_stack": goals,
        "active_entities": entities,
        "temporary_tactics": tactics,
        "active_context_summary": active_context_summary,
        "context_usage": context_usage,
    }))
}

fn build_active_context_summary(session_id: &str) -> Option<Value> {
    let conn = db::open_readonly(&db::chat_db_path())?;
    let rows = db::query_to_json_array(
        &conn,
        "SELECT summary_id, parent_summary_id, status, summary_kind, persona_scope, \
                covered_from_message_id, covered_to_message_id, first_kept_message_id, \
                covered_to_sequence_no, session_origin, summary_text, prompt_profile, \
                model_provider, model_id, token_count_before, token_count_after, \
                quality_status, created_at_ms, updated_at_ms \
         FROM chat_context_summaries \
         WHERE session_id = ?1 \
           AND summary_kind = 'token_budget' \
           AND COALESCE(persona_scope, '') = '' \
           AND status = 'active' \
         ORDER BY covered_to_sequence_no DESC, updated_at_ms DESC \
         LIMIT 1",
        rusqlite::params![session_id],
    );
    rows.into_iter().next()
}

fn build_latest_context_usage(session_id: &str) -> Option<Value> {
    let conn = db::open_readonly(&db::runtime_trace_db_path())?;
    let rows = db::query_to_json_array(
        &conn,
        "SELECT notification_id, turn_id, payload_json, created_at_ms \
         FROM runtime_notifications \
         WHERE session_id = ?1 AND channel = 'context_usage' \
         ORDER BY notification_id DESC \
         LIMIT 1",
        rusqlite::params![session_id],
    );
    let row = rows.into_iter().next()?;
    let row_obj = row.as_object()?;
    let payload = row_obj.get("payload_json")?.clone();
    let mut usage = match payload {
        Value::String(text) => serde_json::from_str::<Value>(&text).ok()?,
        Value::Object(_) => payload,
        _ => return None,
    };
    if let Some(obj) = usage.as_object_mut() {
        if !obj.contains_key("turn_id") {
            obj.insert(
                "turn_id".into(),
                row_obj.get("turn_id").cloned().unwrap_or(Value::Null),
            );
        }
        obj.insert(
            "notification_id".into(),
            row_obj
                .get("notification_id")
                .cloned()
                .unwrap_or(Value::Null),
        );
        obj.insert(
            "created_at_ms".into(),
            row_obj.get("created_at_ms").cloned().unwrap_or(Value::Null),
        );
    }
    Some(usage)
}
