use axum::body::Body;
use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

use crate::db;

const DEFAULT_USER_ID: &str = "default_user";

#[derive(Deserialize)]
pub struct HistoryQuery {
    pub user_id: Option<String>,
    pub session_id: Option<String>,
}

#[derive(Deserialize)]
pub struct AttachmentContentQuery {
    pub user_id: Option<String>,
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

/// Native GET /api/messages/session/:session_id/attachments/:attachment_id/content.
pub async fn attachment_content(
    Path((session_id, attachment_id)): Path<(String, String)>,
    Query(params): Query<AttachmentContentQuery>,
) -> Response {
    let user_id = params
        .user_id
        .unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let sid = session_id.clone();
    let aid = attachment_id.clone();
    match tokio::task::spawn_blocking(move || load_attachment_response(&user_id, &sid, &aid)).await
    {
        Ok(Some(response)) => response,
        _ => (StatusCode::NOT_FOUND, "Attachment not found").into_response(),
    }
}

fn load_attachment_response(
    user_id: &str,
    session_id: &str,
    attachment_id: &str,
) -> Option<Response> {
    let conn = db::open_readonly(&db::chat_db_path())?;
    let metadata = query_attachment_metadata(
        &conn,
        &db::magi_base_dir(),
        user_id,
        session_id,
        attachment_id,
    )?;
    let bytes = std::fs::read(&metadata.absolute_path).ok()?;

    let mut builder = Response::builder().status(StatusCode::OK);
    builder = builder.header("content-type", metadata.mime_type.as_str());
    builder = builder.header(
        "content-disposition",
        format!(
            "inline; filename=\"{}\"",
            sanitize_header_filename(&metadata.original_name)
        ),
    );
    builder.body(Body::from(bytes)).ok()
}

struct AttachmentMetadata {
    mime_type: String,
    original_name: String,
    absolute_path: std::path::PathBuf,
}

fn query_attachment_metadata(
    conn: &Connection,
    base_dir: &std::path::Path,
    user_id: &str,
    session_id: &str,
    attachment_id: &str,
) -> Option<AttachmentMetadata> {
    let mut stmt = conn
        .prepare(
            "SELECT a.mime_type, a.original_name, a.storage_rel_path \
         FROM chat_attachments a \
         JOIN chat_messages m ON m.message_id = a.message_id \
         WHERE a.user_id = ?1 AND a.session_id = ?2 AND a.attachment_id = ?3 \
           AND m.is_visible = 1 \
         LIMIT 1",
        )
        .ok()?;

    stmt.query_row(
        rusqlite::params![user_id, session_id, attachment_id],
        |row| {
            let mime_type = row.get::<_, String>(0)?;
            let original_name = row.get::<_, String>(1)?;
            let storage_rel_path = row.get::<_, String>(2)?;
            let absolute_path = base_dir.join(&storage_rel_path);
            Ok(AttachmentMetadata {
                mime_type,
                original_name,
                absolute_path,
            })
        },
    )
    .ok()
}

fn sanitize_header_filename(value: &str) -> String {
    value.replace('\\', "_").replace('"', "_")
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
    let trace_summaries = load_trace_summaries(user_id, session_id, &turn_ids_with_trace);
    let turn_ux_preferences = load_turn_ux_preferences(&conn, user_id, session_id);

    // Load messages
    let mut stmt = match conn.prepare(
        "SELECT message_id, session_id, turn_id, user_id, role, message_kind, \
                content_text, payload_json, is_final, is_visible, created_at_ms, \
                sequence_no, replaces_message_id, replaced_by_message_id, reply_to_message_id, \
                label_json \
         FROM chat_messages \
         WHERE user_id = ?1 AND session_id = ?2 \
                     AND is_visible = 1 \
                     AND (replaced_by_message_id IS NULL OR message_kind = 'assistant_interim') \
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
                (
                    r.role.as_str(),
                    r.message_kind.as_str(),
                    r.content_text.as_str(),
                ),
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
                "todo_state"
                | "plan_state"
                | "permission_request"
                | "ask_request"
                | "background_task_completion"
                | "status_note"
                | "system_notice" => ("status", row.role.as_str()),
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

            if !payload_is_empty(&payload) {
                msg["payload"] = payload.clone();
            }
            if let Some(tid) = turn_id {
                if let Some(prefs) = turn_ux_preferences.get(tid) {
                    if let Some(mode) = prefs.get("trace_display_mode").and_then(|v| v.as_str()) {
                        if !mode.is_empty() {
                            msg["trace_display_mode"] = json!(mode);
                        }
                    }
                    if let Some(allow) = prefs.get("allow_trace_collapse").and_then(|v| v.as_bool())
                    {
                        msg["allow_trace_collapse"] = json!(allow);
                    }
                }
                if kind == "assistant" {
                    if let Some(summary) = trace_summaries.get(tid) {
                        msg["trace_summary"] = summary.clone();
                        msg["trace_available"] = json!(summary
                            .get("trace_available")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(trace_available));
                    }
                }
            }

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
fn load_turns_with_trace(user_id: &str, session_id: &str) -> HashSet<String> {
    let trace_path = db::runtime_trace_db_path();
    if !trace_path.exists() {
        return HashSet::new();
    }
    let conn = match Connection::open_with_flags(&trace_path, OpenFlags::SQLITE_OPEN_READ_ONLY) {
        Ok(c) => c,
        Err(_) => return HashSet::new(),
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

fn load_trace_summaries(
    user_id: &str,
    session_id: &str,
    turn_ids: &HashSet<String>,
) -> HashMap<String, Value> {
    turn_ids
        .iter()
        .filter_map(|turn_id| {
            let snapshot = super::trace::build_trace_snapshot(user_id, session_id, turn_id);
            let summary = snapshot
                .get("trace")
                .and_then(|trace| trace.get("summary"))
                .cloned()?;
            Some((turn_id.clone(), summary))
        })
        .collect()
}

fn load_turn_ux_preferences(
    conn: &Connection,
    user_id: &str,
    session_id: &str,
) -> HashMap<String, Value> {
    let mut stmt = match conn.prepare(
        "SELECT turn_id, ux_plan_json FROM chat_turns \
         WHERE user_id = ?1 AND session_id = ?2",
    ) {
        Ok(s) => s,
        Err(_) => return HashMap::new(),
    };
    stmt.query_map(rusqlite::params![user_id, session_id], |row| {
        let turn_id: String = row.get(0)?;
        let raw: Option<String> = row.get(1)?;
        let parsed = raw
            .as_deref()
            .and_then(|value| serde_json::from_str::<Value>(value).ok())
            .unwrap_or_else(|| json!({}));
        Ok((turn_id, parsed))
    })
    .ok()
    .map(|iter| iter.filter_map(|r| r.ok()).collect())
    .unwrap_or_default()
}

fn payload_is_empty(payload: &Value) -> bool {
    match payload {
        Value::Null => true,
        Value::Object(map) => map.is_empty(),
        _ => false,
    }
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
    let user_id = body.user_id.unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let workspace_path = body.workspace_path.clone();
    let sid = session_id.clone();
    let result = tokio::task::spawn_blocking(move || {
        do_update_workspace(&user_id, &sid, workspace_path.as_deref())
    })
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

fn do_update_workspace(
    user_id: &str,
    session_id: &str,
    workspace_path: Option<&str>,
) -> Option<Value> {
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

    let user_id = body.user_id.as_deref().unwrap_or(DEFAULT_USER_ID);

    db::emit_notification(
        "chat_message_upserted",
        user_id,
        session_id,
        &json!({
            "user_id": user_id,
            "session_id": session_id,
            "message_id": message_id,
        }),
    );

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
    let user_id = q.user_id.unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let sid = session_id.clone();
    let mid = message_id.clone();
    let uid = user_id.clone();
    let result = tokio::task::spawn_blocking(move || do_hide_message(&sid, &mid, &uid))
        .await
        .unwrap_or(false);
    if result {
        (
            StatusCode::OK,
            Json(json!({
                "success": true,
                "user_id": user_id,
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

fn do_hide_message(session_id: &str, message_id: &str, user_id: &str) -> bool {
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
        db::emit_notification(
            "chat_message_hidden",
            user_id,
            session_id,
            &json!({
                "user_id": user_id,
                "session_id": session_id,
                "message_id": message_id,
            }),
        );
        true
    } else {
        false
    }
}

#[cfg(test)]
mod tests {
    use super::query_attachment_metadata;
    use rusqlite::Connection;
    use std::fs;

    #[test]
    fn attachment_metadata_requires_visible_message() {
        let temp_root =
            std::env::temp_dir().join(format!("magi-attachment-test-{}", uuid::Uuid::new_v4()));
        let chat_root = temp_root
            .join("data")
            .join("resources")
            .join("chat")
            .join("images")
            .join("session-1")
            .join("turn-1");
        fs::create_dir_all(&chat_root).unwrap();
        let attachment_file = chat_root.join("att-1__photo.png");
        fs::write(&attachment_file, b"png").unwrap();

        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "CREATE TABLE chat_messages (message_id TEXT PRIMARY KEY, is_visible INTEGER NOT NULL);\
             CREATE TABLE chat_attachments (\
                attachment_id TEXT PRIMARY KEY,\
                session_id TEXT NOT NULL,\
                message_id TEXT NOT NULL,\
                user_id TEXT NOT NULL,\
                mime_type TEXT NOT NULL,\
                original_name TEXT NOT NULL,\
                storage_rel_path TEXT NOT NULL\
             );",
        ).unwrap();
        conn.execute(
            "INSERT INTO chat_messages (message_id, is_visible) VALUES (?1, 1)",
            rusqlite::params!["msg-1"],
        )
        .unwrap();
        let rel_path = attachment_file
            .strip_prefix(&temp_root)
            .unwrap()
            .to_string_lossy()
            .replace('\\', "/");
        conn.execute(
            "INSERT INTO chat_attachments (attachment_id, session_id, message_id, user_id, mime_type, original_name, storage_rel_path) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            rusqlite::params!["att-1", "session-1", "msg-1", "local_user", "image/png", "photo.png", rel_path],
        ).unwrap();

        let metadata =
            query_attachment_metadata(&conn, &temp_root, "local_user", "session-1", "att-1")
                .unwrap();
        assert_eq!(metadata.mime_type, "image/png");
        assert_eq!(metadata.absolute_path, attachment_file);

        conn.execute(
            "UPDATE chat_messages SET is_visible = 0 WHERE message_id = ?1",
            rusqlite::params!["msg-1"],
        )
        .unwrap();
        assert!(
            query_attachment_metadata(&conn, &temp_root, "local_user", "session-1", "att-1")
                .is_none()
        );

        let _ = fs::remove_dir_all(&temp_root);
    }
}
