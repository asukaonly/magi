use axum::body::Body;
use axum::extract::{Multipart, Path, Query};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use rusqlite::Connection;
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::path::{Path as FsPath, PathBuf};

use crate::db;

use super::common::DEFAULT_USER_ID;

const MAX_IMAGE_ATTACHMENT_BYTES: usize = 20 * 1024 * 1024;
const MAX_FILE_ATTACHMENT_BYTES: usize = 50 * 1024 * 1024;
pub const MAX_ATTACHMENT_UPLOAD_BODY_BYTES: usize = 55 * 1024 * 1024;

#[derive(Clone, Copy)]
enum AttachmentKind {
    Image,
    Pdf,
    TextFile,
}

impl AttachmentKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::Image => "image",
            Self::Pdf => "pdf",
            Self::TextFile => "text_file",
        }
    }
}

struct UploadRequest {
    user_id: String,
    session_id: String,
    turn_id: String,
    original_name: String,
    mime_type: String,
    content: Vec<u8>,
}

struct StoredAttachment {
    attachment_id: String,
    original_name: String,
    mime_type: String,
    size_bytes: usize,
    storage_path: PathBuf,
    sha256: String,
}

#[derive(Deserialize)]
pub struct AttachmentContentQuery {
    pub user_id: Option<String>,
}

pub async fn upload_attachment(
    Path(session_id): Path<String>,
    mut multipart: Multipart,
) -> (StatusCode, Json<Value>) {
    let mut user_id = DEFAULT_USER_ID.to_string();
    let mut turn_id: Option<String> = None;
    let mut original_name: Option<String> = None;
    let mut mime_type: Option<String> = None;
    let mut content: Option<Vec<u8>> = None;

    loop {
        let next_field = match multipart.next_field().await {
            Ok(field) => field,
            Err(_) => return bad_request("Invalid multipart payload"),
        };
        let Some(field) = next_field else {
            break;
        };
        let field_name = field.name().unwrap_or("").to_string();
        match field_name.as_str() {
            "user_id" => match field.text().await {
                Ok(value) => {
                    let normalized = value.trim();
                    if !normalized.is_empty() {
                        user_id = normalized.to_string();
                    }
                }
                Err(_) => return bad_request("Invalid user_id field"),
            },
            "turn_id" => match field.text().await {
                Ok(value) => turn_id = Some(value.trim().to_string()),
                Err(_) => return bad_request("Invalid turn_id field"),
            },
            "file" => {
                original_name = field.file_name().map(str::to_string);
                mime_type = field.content_type().map(|value| value.to_string());
                match field.bytes().await {
                    Ok(bytes) => content = Some(bytes.to_vec()),
                    Err(_) => return bad_request("Invalid file field"),
                }
            }
            _ => {
                let _ = field.bytes().await;
            }
        }
    }

    let request = match build_upload_request(
        user_id,
        session_id,
        turn_id,
        original_name,
        mime_type,
        content,
    ) {
        Ok(value) => value,
        Err(message) => return bad_request(&message),
    };

    let result = tokio::task::spawn_blocking(move || persist_upload(request))
        .await
        .ok()
        .and_then(Result::ok);

    match result {
        Some(response) => (StatusCode::OK, Json(response)),
        None => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({ "detail": "Failed to upload attachment" })),
        ),
    }
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

    let row = stmt
        .query_row(
            rusqlite::params![user_id, session_id, attachment_id],
            |row| {
                let mime_type = row.get::<_, String>(0)?;
                let original_name = row.get::<_, String>(1)?;
                let storage_rel_path = row.get::<_, String>(2)?;
                Ok((mime_type, original_name, storage_rel_path))
            },
        )
        .ok()?;
    let (mime_type, original_name, storage_rel_path) = row;

    let absolute_path = resolve_safe_attachment_path(base_dir, &storage_rel_path)?;
    Some(AttachmentMetadata {
        mime_type,
        original_name,
        absolute_path,
    })
}

/// Resolve `storage_rel_path` against `base_dir` and confirm the result is
/// confined to `base_dir` after canonicalisation. Returns `None` if:
///
/// - `storage_rel_path` is absolute (which would discard `base_dir` via
///   `Path::join`'s "absolute wins" semantics),
/// - `storage_rel_path` resolves outside `base_dir` (`..` traversal or
///   symlink escape),
/// - either side fails to canonicalise (file missing, permission denied).
///
/// This is defence-in-depth: `persist_upload()` already constrains uploads to
/// `{base_dir}/data/resources/chat/{images,files}/{session}/{turn}/`, but
/// `chat_attachments.storage_rel_path` is also written by the Python backend
/// and (transitively) by plugins. A canonicalisation check at the read site
/// stops any future writer that forgets to validate.
fn resolve_safe_attachment_path(base_dir: &FsPath, storage_rel_path: &str) -> Option<PathBuf> {
    // Reject absolute paths up front — `base_dir.join(abs)` would silently
    // discard `base_dir` on Unix and behave inconsistently on Windows.
    let rel = FsPath::new(storage_rel_path);
    if rel.is_absolute() {
        return None;
    }
    let joined = base_dir.join(rel);

    // Canonicalise both sides so the prefix check sees the same form
    // (resolves `..`, symlinks, and any case-folding the FS performs).
    let canonical_base = std::fs::canonicalize(base_dir).ok()?;
    let canonical_path = std::fs::canonicalize(&joined).ok()?;

    if canonical_path.starts_with(&canonical_base) {
        Some(canonical_path)
    } else {
        None
    }
}

fn build_upload_request(
    user_id: String,
    session_id: String,
    turn_id: Option<String>,
    original_name: Option<String>,
    mime_type: Option<String>,
    content: Option<Vec<u8>>,
) -> Result<UploadRequest, String> {
    let turn_id = normalize_path_component(turn_id.unwrap_or_default(), "turn_id")?;
    let session_id = normalize_path_component(session_id, "session_id")?;
    let content = content.ok_or_else(|| "Attachment file is required".to_string())?;
    if content.is_empty() {
        return Err("Empty file is not allowed.".to_string());
    }

    Ok(UploadRequest {
        user_id: if user_id.trim().is_empty() {
            DEFAULT_USER_ID.to_string()
        } else {
            user_id.trim().to_string()
        },
        session_id,
        turn_id,
        original_name: original_name.unwrap_or_default(),
        mime_type: mime_type.unwrap_or_else(|| "application/octet-stream".to_string()),
        content,
    })
}

fn persist_upload(request: UploadRequest) -> Result<Value, String> {
    let base_dir = db::magi_base_dir();
    let normalized_name = sanitize_original_name(&request.original_name);
    let normalized_mime_type = normalize_mime_type(&request.mime_type);
    let attachment_kind = classify_attachment_kind(&normalized_name, &normalized_mime_type)
        .ok_or_else(|| "Unsupported attachment type.".to_string())?;

    if matches!(attachment_kind, AttachmentKind::Image)
        && request.content.len() > MAX_IMAGE_ATTACHMENT_BYTES
    {
        return Err("Image attachment exceeds the 20 MB limit.".to_string());
    }
    if !matches!(attachment_kind, AttachmentKind::Image)
        && request.content.len() > MAX_FILE_ATTACHMENT_BYTES
    {
        return Err("File attachment exceeds the 50 MB limit.".to_string());
    }

    let stored = store_attachment(
        &base_dir,
        attachment_kind,
        &request.session_id,
        &request.turn_id,
        &normalized_name,
        &normalized_mime_type,
        &request.content,
    )?;

    let attachment_payload = build_attachment_payload(attachment_kind, stored)?;

    Ok(json!({
        "success": true,
        "message": "Attachment uploaded",
        "data": {
            "user_id": request.user_id,
            "session_id": request.session_id,
            "turn_id": request.turn_id,
            "attachment": attachment_payload,
        }
    }))
}

fn build_attachment_payload(
    attachment_kind: AttachmentKind,
    stored: StoredAttachment,
) -> Result<Value, String> {
    let attachment_id = stored.attachment_id.clone();
    let storage_path = stored.storage_path.to_string_lossy().into_owned();
    let base_payload = json!({
        "attachment_id": attachment_id,
        "kind": attachment_kind.as_str(),
        "original_name": stored.original_name,
        "mime_type": stored.mime_type,
        "size_bytes": stored.size_bytes,
        "storage_path": storage_path,
        "sha256": stored.sha256,
    });

    match attachment_kind {
        AttachmentKind::Image => Ok(json_merge(
            base_payload,
            json!({
                "parse_status": "not_applicable",
            }),
        )),
        AttachmentKind::Pdf | AttachmentKind::TextFile => Ok(json_merge(
            base_payload,
            json!({
                "parse_status": "pending",
            }),
        )),
    }
}

fn store_attachment(
    base_dir: &FsPath,
    attachment_kind: AttachmentKind,
    session_id: &str,
    turn_id: &str,
    original_name: &str,
    mime_type: &str,
    content: &[u8],
) -> Result<StoredAttachment, String> {
    let attachment_id = uuid::Uuid::new_v4().simple().to_string();
    let root_dir = match attachment_kind {
        AttachmentKind::Image => chat_images_dir(base_dir),
        AttachmentKind::Pdf | AttachmentKind::TextFile => chat_files_dir(base_dir),
    };
    let target_dir = root_dir.join(session_id).join(turn_id);
    std::fs::create_dir_all(&target_dir)
        .map_err(|_| "Failed to prepare attachment storage".to_string())?;
    let target_path = target_dir.join(format!("{attachment_id}__{original_name}"));
    std::fs::write(&target_path, content)
        .map_err(|_| "Failed to store attachment content".to_string())?;
    let sha256 = format!("{:x}", Sha256::digest(content));
    Ok(StoredAttachment {
        attachment_id,
        original_name: original_name.to_string(),
        mime_type: mime_type.to_string(),
        size_bytes: content.len(),
        storage_path: target_path,
        sha256,
    })
}

fn normalize_path_component(value: String, label: &str) -> Result<String, String> {
    let normalized = value.trim().to_string();
    if normalized.is_empty() {
        return Err(format!("{label} is required"));
    }
    if normalized.contains('/') || normalized.contains('\\') {
        return Err(format!("{label} must not contain path separators"));
    }
    Ok(normalized)
}

fn normalize_mime_type(value: &str) -> String {
    let normalized = value.trim().to_ascii_lowercase();
    if normalized.is_empty() {
        "application/octet-stream".to_string()
    } else {
        normalized
    }
}

fn sanitize_original_name(original_name: &str) -> String {
    let candidate = FsPath::new(original_name)
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .trim();
    let source = if candidate.is_empty() {
        "attachment"
    } else {
        candidate
    };
    let safe_name = source
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-') {
                ch
            } else {
                '_'
            }
        })
        .collect::<String>()
        .trim_matches(|ch| ch == '.' || ch == '_')
        .to_string();
    if safe_name.is_empty() {
        "attachment".to_string()
    } else {
        safe_name
    }
}

fn classify_attachment_kind(original_name: &str, mime_type: &str) -> Option<AttachmentKind> {
    let extension = FsPath::new(original_name)
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| format!(".{}", value.to_ascii_lowercase()))
        .unwrap_or_default();
    if is_supported_image_mime(mime_type) || is_supported_image_extension(&extension) {
        return Some(AttachmentKind::Image);
    }
    if mime_type == "application/pdf" || extension == ".pdf" {
        return Some(AttachmentKind::Pdf);
    }
    if mime_type.starts_with("text/")
        || is_supported_text_mime(mime_type)
        || is_supported_text_extension(&extension)
    {
        return Some(AttachmentKind::TextFile);
    }
    None
}

fn is_supported_image_mime(mime_type: &str) -> bool {
    matches!(mime_type, "image/jpeg" | "image/png" | "image/webp")
}

fn is_supported_image_extension(extension: &str) -> bool {
    matches!(extension, ".jpeg" | ".jpg" | ".png" | ".webp")
}

fn is_supported_text_mime(mime_type: &str) -> bool {
    matches!(
        mime_type,
        "application/json"
            | "application/ld+json"
            | "application/sql"
            | "application/toml"
            | "application/x-httpd-php"
            | "application/x-sh"
            | "application/xml"
            | "application/yaml"
            | "text/csv"
            | "text/html"
            | "text/javascript"
            | "text/jsx"
            | "text/markdown"
            | "text/plain"
            | "text/tsx"
            | "text/typescript"
            | "text/x-c"
            | "text/x-c++"
            | "text/x-go"
            | "text/x-java-source"
            | "text/x-python"
            | "text/x-ruby"
            | "text/x-rust"
            | "text/x-shellscript"
            | "text/xml"
    )
}

fn is_supported_text_extension(extension: &str) -> bool {
    matches!(
        extension,
        ".c" | ".cc"
            | ".cpp"
            | ".css"
            | ".csv"
            | ".go"
            | ".h"
            | ".hpp"
            | ".html"
            | ".ini"
            | ".java"
            | ".js"
            | ".json"
            | ".kt"
            | ".log"
            | ".md"
            | ".mjs"
            | ".php"
            | ".py"
            | ".rb"
            | ".rs"
            | ".sh"
            | ".sql"
            | ".swift"
            | ".toml"
            | ".ts"
            | ".tsx"
            | ".txt"
            | ".xml"
            | ".yaml"
            | ".yml"
    )
}

fn chat_images_dir(base_dir: &FsPath) -> PathBuf {
    base_dir
        .join("data")
        .join("resources")
        .join("chat")
        .join("images")
}

fn chat_files_dir(base_dir: &FsPath) -> PathBuf {
    base_dir
        .join("data")
        .join("resources")
        .join("chat")
        .join("files")
}

fn json_merge(mut base: Value, extra: Value) -> Value {
    if let (Some(base_object), Some(extra_object)) = (base.as_object_mut(), extra.as_object()) {
        for (key, value) in extra_object {
            base_object.insert(key.clone(), value.clone());
        }
    }
    base
}

fn bad_request(message: &str) -> (StatusCode, Json<Value>) {
    (StatusCode::BAD_REQUEST, Json(json!({ "detail": message })))
}

fn sanitize_header_filename(value: &str) -> String {
    value.replace('\\', "_").replace('"', "_")
}

#[cfg(test)]
mod tests {
    use super::{
        build_attachment_payload, query_attachment_metadata, sanitize_original_name,
        AttachmentKind, StoredAttachment,
    };
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
        )
        .unwrap();
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
        )
        .unwrap();

        let metadata =
            query_attachment_metadata(&conn, &temp_root, "local_user", "session-1", "att-1")
                .unwrap();
        assert_eq!(metadata.mime_type, "image/png");
        // Both sides go through std::fs::canonicalize after the path-safety
        // gate, so the expected path needs to be canonicalised too — on
        // macOS `/var/folders/...` resolves to `/private/var/folders/...`.
        assert_eq!(
            metadata.absolute_path,
            std::fs::canonicalize(&attachment_file).unwrap()
        );

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

    #[test]
    fn text_attachment_upload_defers_parsing_to_python_runtime() {
        let temp_root = std::env::temp_dir().join(format!(
            "magi-text-attachment-test-{}",
            uuid::Uuid::new_v4()
        ));
        fs::create_dir_all(&temp_root).unwrap();
        let file_path = temp_root.join("notes.txt");
        fs::write(&file_path, "hello rust attachment parser").unwrap();

        let payload = build_attachment_payload(
            AttachmentKind::TextFile,
            StoredAttachment {
                attachment_id: "att-1".to_string(),
                original_name: "notes.txt".to_string(),
                mime_type: "text/plain".to_string(),
                size_bytes: 28,
                storage_path: file_path,
                sha256: "sha".to_string(),
            },
        )
        .unwrap();
        assert_eq!(payload["parse_status"], "pending");
        assert!(payload.get("derived_text_path").is_none());
        assert!(payload.get("derived_text_excerpt").is_none());

        let _ = fs::remove_dir_all(&temp_root);
    }

    #[test]
    fn pdf_attachment_upload_defers_parsing_to_python_runtime() {
        let temp_root =
            std::env::temp_dir().join(format!("magi-pdf-attachment-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&temp_root).unwrap();
        let file_path = temp_root.join("notes.pdf");
        fs::write(&file_path, b"%PDF-1.4\n").unwrap();

        let payload = build_attachment_payload(
            AttachmentKind::Pdf,
            StoredAttachment {
                attachment_id: "att-1".to_string(),
                original_name: "notes.pdf".to_string(),
                mime_type: "application/pdf".to_string(),
                size_bytes: 9,
                storage_path: file_path,
                sha256: "sha".to_string(),
            },
        )
        .unwrap();
        assert_eq!(payload["parse_status"], "pending");
        assert!(payload.get("page_count").is_none());
        assert!(payload.get("parse_error").is_none());

        let _ = fs::remove_dir_all(&temp_root);
    }

    #[test]
    fn sanitize_original_name_strips_path_segments() {
        assert_eq!(
            sanitize_original_name("../../hello world?.txt"),
            "hello_world_.txt"
        );
    }

    #[test]
    fn attachment_metadata_rejects_path_traversal_in_storage_rel_path() {
        use super::resolve_safe_attachment_path;

        let temp_root = std::env::temp_dir().join(format!(
            "magi-attachment-traversal-{}",
            uuid::Uuid::new_v4()
        ));
        let inside = temp_root.join("data").join("resources").join("inside.bin");
        fs::create_dir_all(inside.parent().unwrap()).unwrap();
        fs::write(&inside, b"ok").unwrap();

        // A sibling file that exists OUTSIDE temp_root — canonicalisation
        // must keep us from reading it via a `..` escape.
        let outside_dir =
            std::env::temp_dir().join(format!("magi-attachment-outside-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&outside_dir).unwrap();
        let outside = outside_dir.join("secret.bin");
        fs::write(&outside, b"leak").unwrap();

        // Sanity: a clean relative path resolves.
        assert!(resolve_safe_attachment_path(&temp_root, "data/resources/inside.bin").is_some());

        // Path traversal escaping base_dir → rejected.
        let escape_rel = format!(
            "../{}/secret.bin",
            outside_dir.file_name().unwrap().to_string_lossy()
        );
        assert!(resolve_safe_attachment_path(&temp_root, &escape_rel).is_none());

        // Absolute path → rejected before canonicalisation discards base_dir.
        let absolute_rel = outside.to_string_lossy().to_string();
        assert!(resolve_safe_attachment_path(&temp_root, &absolute_rel).is_none());

        // Non-existent path → None (canonicalize fails). Manifests as 404.
        assert!(resolve_safe_attachment_path(&temp_root, "does/not/exist.bin").is_none());

        let _ = fs::remove_dir_all(&temp_root);
        let _ = fs::remove_dir_all(&outside_dir);
    }
}
