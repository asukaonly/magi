use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use rusqlite::Connection;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::db;

use super::common::DEFAULT_USER_ID;

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
