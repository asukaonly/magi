use axum::body::Body;
use axum::extract::{Multipart, Path, Query};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use regex::bytes::Regex as BytesRegex;
use regex::Regex;
use rusqlite::Connection;
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::path::{Path as FsPath, PathBuf};
use std::sync::OnceLock;

use crate::db;

use super::common::DEFAULT_USER_ID;

const MAX_IMAGE_ATTACHMENT_BYTES: usize = 20 * 1024 * 1024;
const MAX_FILE_ATTACHMENT_BYTES: usize = 50 * 1024 * 1024;
pub const MAX_ATTACHMENT_UPLOAD_BODY_BYTES: usize = 55 * 1024 * 1024;
const DEFAULT_TEXT_ATTACHMENT_MAX_CHARS: usize = 120_000;
const DEFAULT_PDF_ATTACHMENT_MAX_CHARS: usize = 120_000;

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

struct ParsedTextAttachment {
    text: String,
    encoding: String,
    character_count: usize,
    truncated: bool,
    excerpt: String,
}

struct ParsedPdfAttachment {
    text: String,
    character_count: usize,
    truncated: bool,
    excerpt: String,
    page_count: usize,
    extraction_succeeded: bool,
    error: Option<String>,
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

    let attachment_payload = build_attachment_payload(
        &base_dir,
        attachment_kind,
        &request.session_id,
        &request.turn_id,
        stored,
    )?;

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
    base_dir: &FsPath,
    attachment_kind: AttachmentKind,
    session_id: &str,
    turn_id: &str,
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
        AttachmentKind::TextFile => {
            let parsed = parse_text_attachment(&stored.storage_path)?;
            let derived_text_path = write_derived_text(
                base_dir,
                session_id,
                turn_id,
                &attachment_id,
                &parsed.text,
            )?;
            Ok(json_merge(
                base_payload,
                json!({
                    "parse_status": "parsed",
                    "derived_text_path": derived_text_path.to_string_lossy().into_owned(),
                    "derived_text_excerpt": parsed.excerpt,
                    "character_count": parsed.character_count,
                    "truncated": parsed.truncated,
                    "encoding": parsed.encoding,
                }),
            ))
        }
        AttachmentKind::Pdf => {
            let parsed = parse_pdf_attachment(&stored.storage_path)?;
            let mut payload = json_merge(
                base_payload,
                json!({
                    "parse_status": if parsed.extraction_succeeded { "parsed" } else { "failed" },
                    "derived_text_excerpt": parsed.excerpt,
                    "character_count": parsed.character_count,
                    "truncated": parsed.truncated,
                    "page_count": parsed.page_count,
                    "extraction_succeeded": parsed.extraction_succeeded,
                }),
            );
            if parsed.extraction_succeeded {
                let derived_text_path = write_derived_text(
                    base_dir,
                    session_id,
                    turn_id,
                    &attachment_id,
                    &parsed.text,
                )?;
                if let Some(object) = payload.as_object_mut() {
                    object.insert(
                        "derived_text_path".to_string(),
                        Value::String(derived_text_path.to_string_lossy().into_owned()),
                    );
                }
            }
            if let Some(error) = parsed.error {
                if let Some(object) = payload.as_object_mut() {
                    object.insert("parse_error".to_string(), Value::String(error));
                }
            }
            Ok(payload)
        }
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

fn parse_text_attachment(file_path: &FsPath) -> Result<ParsedTextAttachment, String> {
    let content_bytes =
        std::fs::read(file_path).map_err(|_| "Failed to read text attachment".to_string())?;
    let (text, encoding) = decode_text_bytes(&content_bytes)?;
    let character_count = text.chars().count();
    let truncated = character_count > DEFAULT_TEXT_ATTACHMENT_MAX_CHARS;
    let visible_text: String = text.chars().take(DEFAULT_TEXT_ATTACHMENT_MAX_CHARS).collect();
    let excerpt: String = visible_text.chars().take(200).collect();
    Ok(ParsedTextAttachment {
        text: if truncated { visible_text } else { text },
        encoding,
        character_count,
        truncated,
        excerpt,
    })
}

fn decode_text_bytes(content_bytes: &[u8]) -> Result<(String, String), String> {
    if let Ok(text) = String::from_utf8(content_bytes.to_vec()) {
        return Ok((text, "utf-8".to_string()));
    }
    if let Some(stripped) = content_bytes.strip_prefix(&[0xEF, 0xBB, 0xBF]) {
        if let Ok(text) = String::from_utf8(stripped.to_vec()) {
            return Ok((text, "utf-8-sig".to_string()));
        }
    }
    if content_bytes.starts_with(&[0xFF, 0xFE]) || content_bytes.starts_with(&[0xFE, 0xFF]) {
        if let Ok(text) = decode_utf16_bytes(content_bytes) {
            return Ok((text, "utf-16".to_string()));
        }
    }
    let latin1 = content_bytes
        .iter()
        .map(|byte| char::from(*byte))
        .collect::<String>();
    Ok((latin1, "latin-1".to_string()))
}

fn decode_utf16_bytes(content_bytes: &[u8]) -> Result<String, String> {
    if content_bytes.len() < 2 {
        return Err("Invalid UTF-16 content".to_string());
    }
    let little_endian = content_bytes.starts_with(&[0xFF, 0xFE]);
    let data = &content_bytes[2..];
    let mut units = Vec::with_capacity(data.len() / 2);
    for chunk in data.chunks_exact(2) {
        let value = if little_endian {
            u16::from_le_bytes([chunk[0], chunk[1]])
        } else {
            u16::from_be_bytes([chunk[0], chunk[1]])
        };
        units.push(value);
    }
    String::from_utf16(&units).map_err(|_| "Invalid UTF-16 content".to_string())
}

fn parse_pdf_attachment(file_path: &FsPath) -> Result<ParsedPdfAttachment, String> {
    let content_bytes =
        std::fs::read(file_path).map_err(|_| "Failed to read PDF attachment".to_string())?;
    if !content_bytes.starts_with(b"%PDF-") {
        return Ok(ParsedPdfAttachment {
            text: String::new(),
            character_count: 0,
            truncated: false,
            excerpt: String::new(),
            page_count: 0,
            extraction_succeeded: false,
            error: Some("Unsupported PDF format".to_string()),
        });
    }

    let page_count = pdf_page_pattern().find_iter(&content_bytes).count();
    let mut extracted_segments = Vec::new();
    let mut had_unsupported_stream = false;

    for captures in pdf_stream_pattern().captures_iter(&content_bytes) {
        let Some(stream_match) = captures.get(1) else {
            continue;
        };
        let stream_start = captures.get(0).map(|value| value.start()).unwrap_or(0);
        let header_start = stream_start.saturating_sub(200);
        let header_window = &content_bytes[header_start..stream_start];
        if header_window
            .windows(b"/FlateDecode".len())
            .any(|window| window == b"/FlateDecode")
        {
            had_unsupported_stream = true;
            continue;
        }
        extracted_segments.extend(extract_stream_text(stream_match.as_bytes()));
    }

    let normalized_text = extracted_segments
        .into_iter()
        .filter(|segment| !segment.is_empty())
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string();

    if normalized_text.is_empty() {
        return Ok(ParsedPdfAttachment {
            text: String::new(),
            character_count: 0,
            truncated: false,
            excerpt: String::new(),
            page_count,
            extraction_succeeded: false,
            error: Some(if had_unsupported_stream {
                "PDF text extraction requires an uncompressed readable PDF stream".to_string()
            } else {
                "No readable text found in PDF".to_string()
            }),
        });
    }

    let character_count = normalized_text.chars().count();
    let truncated = character_count > DEFAULT_PDF_ATTACHMENT_MAX_CHARS;
    let visible_text: String = normalized_text
        .chars()
        .take(DEFAULT_PDF_ATTACHMENT_MAX_CHARS)
        .collect();
    let excerpt: String = visible_text.chars().take(200).collect();

    Ok(ParsedPdfAttachment {
        text: if truncated { visible_text } else { normalized_text },
        character_count,
        truncated,
        excerpt,
        page_count,
        extraction_succeeded: true,
        error: None,
    })
}

fn extract_stream_text(stream_bytes: &[u8]) -> Vec<String> {
    let stream_text = String::from_utf8_lossy(stream_bytes);
    let mut segments = Vec::new();
    for text_block in pdf_text_block_pattern().captures_iter(&stream_text) {
        let Some(block_match) = text_block.get(1) else {
            continue;
        };
        let mut segment = String::new();
        for literal in pdf_text_string_pattern().find_iter(block_match.as_str()) {
            segment.push_str(&decode_pdf_literal(literal.as_str()));
        }
        let normalized = segment.trim().to_string();
        if !normalized.is_empty() {
            segments.push(normalized);
        }
    }
    segments
}

fn decode_pdf_literal(literal: &str) -> String {
    let inner = literal
        .strip_prefix('(')
        .and_then(|value| value.strip_suffix(')'))
        .unwrap_or(literal);
    let normalized = inner
        .replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\\", "\\");
    pdf_octal_pattern()
        .replace_all(&normalized, |captures: &regex::Captures<'_>| {
            let value = captures
                .get(1)
                .and_then(|matched| u8::from_str_radix(matched.as_str(), 8).ok())
                .map(char::from)
                .unwrap_or('\0');
            value.to_string()
        })
        .into_owned()
}

fn write_derived_text(
    base_dir: &FsPath,
    session_id: &str,
    turn_id: &str,
    attachment_id: &str,
    text: &str,
) -> Result<PathBuf, String> {
    let target_dir = chat_derived_dir(base_dir).join(session_id).join(turn_id);
    std::fs::create_dir_all(&target_dir)
        .map_err(|_| "Failed to prepare derived attachment storage".to_string())?;
    let target_path = target_dir.join(format!("{attachment_id}.txt"));
    std::fs::write(&target_path, text.as_bytes())
        .map_err(|_| "Failed to write derived attachment text".to_string())?;
    Ok(target_path)
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
        ".c"
            | ".cc"
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

fn chat_derived_dir(base_dir: &FsPath) -> PathBuf {
    base_dir
        .join("data")
        .join("resources")
        .join("chat")
        .join("derived")
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

fn pdf_stream_pattern() -> &'static BytesRegex {
    static RE: OnceLock<BytesRegex> = OnceLock::new();
    RE.get_or_init(|| BytesRegex::new(r"(?s)stream\r?\n(.*?)\r?\nendstream").unwrap())
}

fn pdf_page_pattern() -> &'static BytesRegex {
    static RE: OnceLock<BytesRegex> = OnceLock::new();
    RE.get_or_init(|| BytesRegex::new(r"/Type\s*/Page\b").unwrap())
}

fn pdf_text_block_pattern() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?s)BT(.*?)ET").unwrap())
}

fn pdf_text_string_pattern() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\((?:\\.|[^\\)])*\)").unwrap())
}

fn pdf_octal_pattern() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\\([0-7]{1,3})").unwrap())
}

fn sanitize_header_filename(value: &str) -> String {
    value.replace('\\', "_").replace('"', "_")
}

#[cfg(test)]
mod tests {
    use super::{
        parse_pdf_attachment, parse_text_attachment, query_attachment_metadata,
        sanitize_original_name,
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

    #[test]
    fn text_attachment_parser_extracts_excerpt() {
        let temp_root =
            std::env::temp_dir().join(format!("magi-text-attachment-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&temp_root).unwrap();
        let file_path = temp_root.join("notes.txt");
        fs::write(&file_path, "hello rust attachment parser").unwrap();

        let parsed = parse_text_attachment(&file_path).unwrap();
        assert_eq!(parsed.encoding, "utf-8");
        assert_eq!(parsed.excerpt, "hello rust attachment parser");
        assert!(!parsed.truncated);

        let _ = fs::remove_dir_all(&temp_root);
    }

    #[test]
    fn pdf_attachment_parser_reports_missing_text() {
        let temp_root =
            std::env::temp_dir().join(format!("magi-pdf-attachment-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&temp_root).unwrap();
        let file_path = temp_root.join("notes.pdf");
        fs::write(
            &file_path,
            b"%PDF-1.4\n1 0 obj<< /Type /Page >>\nstream\ncompressed\nendstream\n",
        )
        .unwrap();

        let parsed = parse_pdf_attachment(&file_path).unwrap();
        assert!(!parsed.extraction_succeeded);
        assert_eq!(parsed.page_count, 1);
        assert!(parsed.error.is_some());

        let _ = fs::remove_dir_all(&temp_root);
    }

    #[test]
    fn sanitize_original_name_strips_path_segments() {
        assert_eq!(sanitize_original_name("../../hello world?.txt"), "hello_world_.txt");
    }
}
