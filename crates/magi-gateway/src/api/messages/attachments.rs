use axum::body::Body;
use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::Deserialize;

use rusqlite::Connection;

use crate::db;

use super::common::DEFAULT_USER_ID;

#[derive(Deserialize)]
pub struct AttachmentContentQuery {
    pub user_id: Option<String>,
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
