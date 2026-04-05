use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::db;

const DEFAULT_USER_ID: &str = "default_user";

#[derive(Deserialize)]
pub struct HistoryQuery {
    pub user_id: Option<String>,
    pub session_id: Option<String>,
}

/// Native GET /api/messages/history handler — reads chat.db directly.
pub async fn message_history(Query(params): Query<HistoryQuery>) -> Json<Value> {
    let user_id = params
        .user_id
        .unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let session_id = match params.session_id {
        Some(sid) if !sid.is_empty() => sid,
        _ => {
            return Json(json!({
                "user_id": user_id,
                "session_id": null,
                "messages": [],
                "count": 0
            }))
        }
    };

    let result = tokio::task::spawn_blocking(move || query_history(&user_id, &session_id))
        .await
        .unwrap_or_else(|_| {
            json!({
                "user_id": DEFAULT_USER_ID,
                "session_id": null,
                "messages": [],
                "count": 0
            })
        });
    Json(result)
}

pub(super) fn query_history(user_id: &str, session_id: &str) -> Value {
    let db_path = db::chat_db_path();
    if !db_path.exists() {
        return empty_history(user_id, session_id);
    }
    let conn = match Connection::open_with_flags(&db_path, OpenFlags::SQLITE_OPEN_READ_ONLY) {
        Ok(c) => c,
        Err(_) => return empty_history(user_id, session_id),
    };

    // Load turns for trace availability lookup
    let turn_ids_with_trace = load_turns_with_trace(user_id, session_id);

    // Load messages
    let mut stmt = match conn.prepare(
        "SELECT message_id, session_id, turn_id, user_id, role, message_kind, \
                content_text, payload_json, is_final, is_visible, created_at_ms, \
                sequence_no, replaces_message_id, replaced_by_message_id, reply_to_message_id, \
                label_json \
         FROM chat_messages \
         WHERE user_id = ?1 AND session_id = ?2 \
           AND is_visible = 1 AND replaced_by_message_id IS NULL \
         ORDER BY created_at_ms ASC, sequence_no ASC",
    ) {
        Ok(s) => s,
        Err(_) => return empty_history(user_id, session_id),
    };

    // Collect all rows first for reply-to resolution
    struct MsgRow {
        message_id: String,
        turn_id: Option<String>,
        role: String,
        message_kind: String,
        content_text: String,
        payload_json: String,
        created_at_ms: i64,
        reply_to_message_id: Option<String>,
        label_json: Option<String>,
    }

    let rows: Vec<MsgRow> = stmt
        .query_map(rusqlite::params![user_id, session_id], |row| {
            Ok(MsgRow {
                message_id: row.get::<_, String>(0)?,
                turn_id: row.get::<_, Option<String>>(2)?,
                role: row.get::<_, String>(4)?,
                message_kind: row.get::<_, String>(5)?,
                content_text: row.get::<_, Option<String>>(6)?.unwrap_or_default(),
                payload_json: row.get::<_, Option<String>>(7)?.unwrap_or_default(),
                created_at_ms: row.get::<_, i64>(10)?,
                reply_to_message_id: row.get::<_, Option<String>>(14)?,
                label_json: row.get::<_, Option<String>>(15)?,
            })
        })
        .ok()
        .map(|iter| iter.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();

    // Build message_id → basic info map for reply-to resolution
    let msg_by_id: std::collections::HashMap<&str, (&str, &str, &str)> = rows
        .iter()
        .map(|r| {
            (
                r.message_id.as_str(),
                (r.role.as_str(), r.message_kind.as_str(), r.content_text.as_str()),
            )
        })
        .collect();

    let messages: Vec<Value> = rows
        .iter()
        .filter_map(|row| {
            let content = row.content_text.trim();
            let payload: Value = serde_json::from_str(&row.payload_json).unwrap_or(json!({}));
            let attachments = payload
                .get("attachments")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();

            if content.is_empty() && attachments.is_empty() {
                return None;
            }

            let (kind, role) = match row.message_kind.as_str() {
                "user_text" => ("user", "user"),
                "assistant_final" | "assistant_interim" | "assistant_reaction" => {
                    ("assistant", row.role.as_str())
                }
                "status_note" | "system_notice" => ("status", row.role.as_str()),
                _ => return None,
            };

            let turn_id = row.turn_id.as_deref().filter(|s| !s.is_empty());
            let trace_available = turn_id
                .map(|tid| turn_ids_with_trace.contains(tid))
                .unwrap_or(false);

            let label = parse_label(&row.label_json);

            // Resolve reply_to
            let reply_to = row.reply_to_message_id.as_deref().and_then(|rid| {
                let rid = rid.trim();
                if rid.is_empty() {
                    return None;
                }
                msg_by_id.get(rid).map(|(r_role, r_kind, r_content)| {
                    let excerpt: String = r_content.chars().take(160).collect();
                    json!({
                        "message_id": rid,
                        "role": r_role,
                        "message_kind": if r_kind.is_empty() { Value::Null } else { json!(r_kind) },
                        "content_excerpt": excerpt
                    })
                })
            });

            let mut msg = json!({
                "role": role,
                "kind": kind,
                "content": content,
                "timestamp": row.created_at_ms,
                "message_id": row.message_id,
                "message_kind": row.message_kind,
                "turn_id": turn_id,
                "trace_available": trace_available && kind == "assistant",
            });

            if !attachments.is_empty() {
                msg["attachments"] = json!(attachments);
            }
            if let Some(reply) = reply_to {
                msg["reply_to"] = reply;
            }
            if let Some(lbl) = label {
                msg["label"] = lbl;
            }

            Some(msg)
        })
        .collect();

    let count = messages.len();
    json!({
        "user_id": user_id,
        "session_id": session_id,
        "messages": messages,
        "count": count
    })
}

/// Load turn_ids that have trace data in runtime_trace.db.
fn load_turns_with_trace(user_id: &str, session_id: &str) -> std::collections::HashSet<String> {
    let trace_path = db::runtime_trace_db_path();
    if !trace_path.exists() {
        return std::collections::HashSet::new();
    }
    let conn = match Connection::open_with_flags(&trace_path, OpenFlags::SQLITE_OPEN_READ_ONLY) {
        Ok(c) => c,
        Err(_) => return std::collections::HashSet::new(),
    };
    let mut stmt = match conn.prepare(
        "SELECT DISTINCT turn_id FROM trace_turns \
         WHERE user_id = ?1 AND session_id = ?2",
    ) {
        Ok(s) => s,
        Err(_) => return std::collections::HashSet::new(),
    };
    stmt.query_map(rusqlite::params![user_id, session_id], |row| {
        row.get::<_, String>(0)
    })
    .ok()
    .map(|iter| iter.filter_map(|r| r.ok()).collect())
    .unwrap_or_default()
}

fn parse_label(raw: &Option<String>) -> Option<Value> {
    let raw = raw.as_ref()?;
    let parsed: Value = serde_json::from_str(raw).ok()?;
    let obj = parsed.as_object()?;
    let kind = obj.get("kind")?.as_str().filter(|s| !s.is_empty())?;
    let text = obj.get("text")?.as_str().filter(|s| !s.is_empty())?;
    let applied_by = obj.get("applied_by")?.as_str().filter(|s| !s.is_empty())?;
    let source = obj.get("source")?.as_str().filter(|s| !s.is_empty())?;
    let created_at_ms = obj.get("created_at_ms")?.as_i64().filter(|&v| v > 0)?;
    Some(json!({
        "kind": kind,
        "text": text,
        "applied_by": applied_by,
        "source": source,
        "created_at_ms": created_at_ms
    }))
}

fn empty_history(user_id: &str, session_id: &str) -> Value {
    json!({
        "user_id": user_id,
        "session_id": session_id,
        "messages": [],
        "count": 0
    })
}

// ---------------------------------------------------------------------------
// Session mutation handlers
// ---------------------------------------------------------------------------

fn open_chat_db_rw() -> Option<Connection> {
    db::open_readwrite(&db::chat_db_path())
}

#[derive(Deserialize)]
pub struct NewSessionQuery {
    pub user_id: Option<String>,
}

/// POST /api/messages/session/new — create a new chat session.
pub async fn create_session(Query(q): Query<NewSessionQuery>) -> (StatusCode, Json<Value>) {
    let user_id = q.user_id.unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let result = tokio::task::spawn_blocking(move || insert_session(&user_id))
        .await
        .unwrap_or(None);
    match result {
        Some(v) => (StatusCode::CREATED, Json(v)),
        None => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"detail": "Failed to create session"})),
        ),
    }
}

fn insert_session(user_id: &str) -> Option<Value> {
    let conn = open_chat_db_rw()?;
    let session_id = format!("session_{}", uuid::Uuid::new_v4());
    let now_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_millis() as i64;

    conn.execute(
        "INSERT INTO chat_sessions (session_id, user_id, title, title_overridden, summary, \
         created_at_ms, updated_at_ms, last_message_at_ms, last_user_message_at_ms, \
         last_message_preview, last_user_message_preview, message_count, workspace_path, \
         history_version) \
         VALUES (?1, ?2, 'New Session', 0, '', ?3, ?4, NULL, NULL, '', '', 0, NULL, 0)",
        rusqlite::params![session_id, user_id, now_ms, now_ms],
    )
    .ok()?;

    Some(json!({
        "success": true,
        "user_id": user_id,
        "session_id": session_id,
        "workspace_path": null,
    }))
}

#[derive(Deserialize)]
pub struct RenameSessionBody {
    pub user_id: Option<String>,
    pub title: String,
}

/// PATCH /api/messages/session/:session_id — rename session.
pub async fn rename_session(
    Path(session_id): Path<String>,
    Json(body): Json<RenameSessionBody>,
) -> (StatusCode, Json<Value>) {
    let user_id = body.user_id.unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let title = body.title.clone();
    let sid = session_id.clone();
    let result = tokio::task::spawn_blocking(move || do_rename_session(&user_id, &sid, &title))
        .await
        .unwrap_or(None);
    match result {
        Some(v) => (StatusCode::OK, Json(v)),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({"detail": "Session not found"})),
        ),
    }
}

fn do_rename_session(user_id: &str, session_id: &str, title: &str) -> Option<Value> {
    let conn = open_chat_db_rw()?;
    let now_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_millis() as i64;

    let updated = conn
        .execute(
            "UPDATE chat_sessions SET title = ?1, title_overridden = 1, updated_at_ms = ?2 \
             WHERE session_id = ?3 AND user_id = ?4 AND deleted_at_ms IS NULL",
            rusqlite::params![title, now_ms, session_id, user_id],
        )
        .unwrap_or(0);

    if updated == 0 {
        return None;
    }

    Some(json!({
        "success": true,
        "user_id": user_id,
        "session": {
            "session_id": session_id,
            "title": title,
        }
    }))
}

#[derive(Deserialize)]
pub struct UpdateWorkspaceBody {
    pub user_id: Option<String>,
    pub workspace_path: Option<String>,
}

/// PATCH /api/messages/session/:session_id/workspace — update session workspace.
pub async fn update_session_workspace(
    Path(session_id): Path<String>,
    Json(body): Json<UpdateWorkspaceBody>,
) -> (StatusCode, Json<Value>) {
    let user_id = body
        .user_id
        .unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let workspace_path = body.workspace_path.clone();
    let sid = session_id.clone();
    let result =
        tokio::task::spawn_blocking(move || do_update_workspace(&user_id, &sid, workspace_path.as_deref()))
            .await
            .unwrap_or(None);
    match result {
        Some(v) => (StatusCode::OK, Json(v)),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({"detail": "Session not found"})),
        ),
    }
}

fn do_update_workspace(user_id: &str, session_id: &str, workspace_path: Option<&str>) -> Option<Value> {
    let conn = open_chat_db_rw()?;
    let now_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_millis() as i64;

    let updated = conn
        .execute(
            "UPDATE chat_sessions SET workspace_path = ?1, updated_at_ms = ?2 \
             WHERE session_id = ?3 AND user_id = ?4 AND deleted_at_ms IS NULL",
            rusqlite::params![workspace_path, now_ms, session_id, user_id],
        )
        .unwrap_or(0);

    if updated == 0 {
        return None;
    }

    Some(json!({
        "success": true,
        "user_id": user_id,
        "session": {
            "session_id": session_id,
            "workspace_path": workspace_path,
        }
    }))
}

#[derive(Deserialize)]
pub struct MessageLabelBody {
    pub user_id: Option<String>,
    pub kind: String,
    pub text: String,
    pub applied_by: String,
    pub source: String,
    pub created_at_ms: Option<i64>,
}

/// POST /api/messages/session/:session_id/message/:message_id/label
pub async fn set_message_label(
    Path((session_id, message_id)): Path<(String, String)>,
    Json(body): Json<MessageLabelBody>,
) -> (StatusCode, Json<Value>) {
    let _user_id = body
        .user_id
        .clone()
        .unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let sid = session_id.clone();
    let mid = message_id.clone();
    let result = tokio::task::spawn_blocking(move || do_set_label(&sid, &mid, &body))
        .await
        .unwrap_or(None);
    match result {
        Some(v) => (StatusCode::OK, Json(v)),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({"detail": "Message not found"})),
        ),
    }
}

fn do_set_label(session_id: &str, message_id: &str, body: &MessageLabelBody) -> Option<Value> {
    let conn = open_chat_db_rw()?;
    let now_ms = body.created_at_ms.unwrap_or_else(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as i64
    });
    let label = json!({
        "kind": body.kind,
        "text": body.text,
        "applied_by": body.applied_by,
        "source": body.source,
        "created_at_ms": now_ms,
    });
    let label_json = serde_json::to_string(&label).ok()?;

    let updated = conn
        .execute(
            "UPDATE chat_messages SET label_json = ?1 WHERE session_id = ?2 AND message_id = ?3",
            rusqlite::params![label_json, session_id, message_id],
        )
        .unwrap_or(0);
    if updated == 0 {
        return None;
    }

    // Bump history version
    conn.execute(
        "UPDATE chat_sessions SET history_version = history_version + 1 WHERE session_id = ?1",
        rusqlite::params![session_id],
    )
    .ok();

    let user_id = body
        .user_id
        .as_deref()
        .unwrap_or(DEFAULT_USER_ID);

    Some(json!({
        "success": true,
        "message": "Message label updated",
        "data": {
            "user_id": user_id,
            "session_id": session_id,
            "message_id": message_id,
            "label": label,
        }
    }))
}

#[derive(Deserialize)]
pub struct DeleteMessageQuery {
    pub user_id: Option<String>,
}

/// DELETE /api/messages/session/:session_id/message/:message_id — soft-delete message.
pub async fn hide_message(
    Path((session_id, message_id)): Path<(String, String)>,
    Query(q): Query<DeleteMessageQuery>,
) -> (StatusCode, Json<Value>) {
    let user_id = q
        .user_id
        .unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let sid = session_id.clone();
    let mid = message_id.clone();
    let uid = user_id.clone();
    let result = tokio::task::spawn_blocking(move || do_hide_message(&sid, &mid))
        .await
        .unwrap_or(false);
    if result {
        (
            StatusCode::OK,
            Json(json!({
                "success": true,
                "user_id": uid,
                "session_id": session_id,
                "deleted_message_id": message_id,
            })),
        )
    } else {
        (
            StatusCode::NOT_FOUND,
            Json(json!({"detail": "Message not found"})),
        )
    }
}

fn do_hide_message(session_id: &str, message_id: &str) -> bool {
    let conn = match open_chat_db_rw() {
        Some(c) => c,
        None => return false,
    };
    let updated = conn
        .execute(
            "UPDATE chat_messages SET is_visible = 0 \
             WHERE session_id = ?1 AND message_id = ?2 AND is_visible = 1",
            rusqlite::params![session_id, message_id],
        )
        .unwrap_or(0);
    if updated > 0 {
        conn.execute(
            "UPDATE chat_sessions SET history_version = history_version + 1 WHERE session_id = ?1",
            rusqlite::params![session_id],
        )
        .ok();
        true
    } else {
        false
    }
}
