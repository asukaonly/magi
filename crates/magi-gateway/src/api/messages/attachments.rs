use axum::body::Body;
use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use serde::Deserialize;
use std::io::{Seek, SeekFrom};
use std::path::{Path as FsPath, PathBuf};
use std::time::Duration;
use tokio::io::AsyncReadExt;
use tokio_util::io::ReaderStream;

use crate::api::state::ApiState;
use crate::db;
use serde_json::json;

use super::common::DEFAULT_USER_ID;

pub const MAX_ATTACHMENT_UPLOAD_BODY_BYTES: usize = 55 * 1024 * 1024;

#[derive(Deserialize)]
pub struct AttachmentContentQuery {
    pub user_id: Option<String>,
}

/// Native GET /api/messages/session/:session_id/attachments/:attachment_id/content.
pub async fn attachment_content(
    State(state): State<ApiState>,
    Path((session_id, attachment_id)): Path<(String, String)>,
    Query(params): Query<AttachmentContentQuery>,
    headers: HeaderMap,
) -> Response {
    let user_id = params
        .user_id
        .unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let range = headers
        .get(header::RANGE)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let result = match state
        .ipc_client
        .request_with_timeout(
            "chat.resolve_attachment",
            Some(json!({
                "user_id": user_id, "session_id": session_id, "attachment_id": attachment_id,
            })),
            Duration::from_secs(30),
        )
        .await
    {
        Ok(value) => value,
        Err(_) => {
            return (
                StatusCode::SERVICE_UNAVAILABLE,
                "Attachment owner unavailable",
            )
                .into_response()
        }
    };
    let resolution: AttachmentResolution = match serde_json::from_value(result) {
        Ok(value) => value,
        Err(_) => {
            return (
                StatusCode::BAD_GATEWAY,
                "Invalid attachment ownership response",
            )
                .into_response()
        }
    };
    let Some(location) = resolution.attachment else {
        return (StatusCode::NOT_FOUND, "Attachment not found").into_response();
    };
    if location.user_id != user_id
        || location.session_id != session_id
        || location.attachment_id != attachment_id
    {
        return (
            StatusCode::BAD_GATEWAY,
            "Attachment ownership does not match the request",
        )
            .into_response();
    }
    match tokio::task::spawn_blocking(move || {
        let base_dir = db::magi_base_dir();
        let metadata = metadata_from_location(&base_dir, location)?;
        let file = open_validated_attachment_file(&base_dir, &metadata.absolute_path)?;
        build_attachment_response(metadata, file, range.as_deref())
    })
    .await
    {
        Ok(Some(response)) => response,
        _ => (StatusCode::NOT_FOUND, "Attachment not found").into_response(),
    }
}

#[derive(Deserialize)]
struct AttachmentResolution {
    attachment: Option<OwnedAttachmentLocation>,
}

#[derive(Deserialize)]
struct OwnedAttachmentLocation {
    user_id: String,
    session_id: String,
    attachment_id: String,
    turn_id: String,
    kind: String,
    original_name: String,
    mime_type: String,
    storage_rel_path: String,
}

fn build_attachment_response(
    metadata: AttachmentMetadata,
    mut file: std::fs::File,
    range: Option<&str>,
) -> Option<Response> {
    let content_length = file.metadata().ok()?.len();
    let parsed_range = match range {
        Some(value) => match parse_byte_range(value, content_length) {
            Ok(value) => value,
            Err(()) => {
                return Response::builder()
                    .status(StatusCode::RANGE_NOT_SATISFIABLE)
                    .header(header::ACCEPT_RANGES, "bytes")
                    .header(header::CONTENT_RANGE, format!("bytes */{content_length}"))
                    .body(Body::empty())
                    .ok();
            }
        },
        None => None,
    };

    let (status, response_length, content_range) = match parsed_range {
        Some((start, end)) => {
            file.seek(SeekFrom::Start(start)).ok()?;
            (
                StatusCode::PARTIAL_CONTENT,
                end - start + 1,
                Some(format!("bytes {start}-{end}/{content_length}")),
            )
        }
        None => (StatusCode::OK, content_length, None),
    };

    let mut builder = Response::builder().status(status);
    builder = builder.header("content-type", metadata.mime_type.as_str());
    builder = builder.header(header::CONTENT_LENGTH, response_length);
    builder = builder.header(header::ACCEPT_RANGES, "bytes");
    if let Some(value) = content_range {
        builder = builder.header(header::CONTENT_RANGE, value);
    }
    builder = builder.header(
        "content-disposition",
        format!(
            "inline; filename=\"{}\"",
            sanitize_header_filename(&metadata.original_name)
        ),
    );
    let stream = ReaderStream::with_capacity(
        tokio::fs::File::from_std(file).take(response_length),
        1024 * 1024,
    );
    builder.body(Body::from_stream(stream)).ok()
}

fn parse_byte_range(value: &str, content_length: u64) -> Result<Option<(u64, u64)>, ()> {
    let Some(specifier) = value.strip_prefix("bytes=") else {
        return Ok(None);
    };
    if specifier.contains(',') {
        return Err(());
    }
    let (start, end) = specifier.split_once('-').ok_or(())?;

    if start.is_empty() {
        let suffix_length = end
            .parse::<u64>()
            .ok()
            .filter(|value| *value > 0)
            .ok_or(())?;
        if content_length == 0 {
            return Err(());
        }
        let suffix_length = suffix_length.min(content_length);
        return Ok(Some((content_length - suffix_length, content_length - 1)));
    }

    let start = start.parse::<u64>().map_err(|_| ())?;
    if start >= content_length {
        return Err(());
    }
    let end = if end.is_empty() {
        content_length - 1
    } else {
        end.parse::<u64>().map_err(|_| ())?.min(content_length - 1)
    };
    if start > end {
        return Err(());
    }
    Ok(Some((start, end)))
}

struct AttachmentMetadata {
    mime_type: String,
    original_name: String,
    absolute_path: std::path::PathBuf,
}

fn metadata_from_location(
    base_dir: &FsPath,
    location: OwnedAttachmentLocation,
) -> Option<AttachmentMetadata> {
    let absolute_path = resolve_managed_attachment_path(
        base_dir,
        &location.session_id,
        &location.turn_id,
        &location.attachment_id,
        &location.kind,
        &location.original_name,
        &location.storage_rel_path,
    )?;
    Some(AttachmentMetadata {
        mime_type: location.mime_type,
        original_name: location.original_name,
        absolute_path,
    })
}

/// Rebuild the only path one attachment identity may own and reject aliases.
fn resolve_managed_attachment_path(
    base_dir: &FsPath,
    session_id: &str,
    turn_id: &str,
    attachment_id: &str,
    kind: &str,
    original_name: &str,
    storage_rel_path: &str,
) -> Option<PathBuf> {
    if !is_safe_asset_component(session_id)
        || !is_safe_asset_component(turn_id)
        || !is_safe_asset_component(attachment_id)
        || !is_exact_filename(original_name)
    {
        return None;
    }
    let canonical_base = std::fs::canonicalize(base_dir).ok()?;
    let asset_type = if kind == "image" { "images" } else { "files" };
    let expected_relative = PathBuf::from("data")
        .join("resources")
        .join("chat")
        .join(asset_type)
        .join(session_id)
        .join(turn_id)
        .join(format!("{attachment_id}__{original_name}"));
    if FsPath::new(storage_rel_path) != expected_relative {
        return None;
    }
    let expected_path = canonical_base.join(&expected_relative);
    let expected_parent = expected_path.parent()?;
    let managed_directories = [
        canonical_base.join("data"),
        canonical_base.join("data").join("resources"),
        canonical_base.join("data").join("resources").join("chat"),
        canonical_base
            .join("data")
            .join("resources")
            .join("chat")
            .join(asset_type),
        canonical_base
            .join("data")
            .join("resources")
            .join("chat")
            .join(asset_type)
            .join(session_id),
        expected_parent.to_path_buf(),
    ];
    if managed_directories
        .iter()
        .any(|path| !is_real_directory(path))
    {
        return None;
    }
    let metadata = std::fs::symlink_metadata(&expected_path).ok()?;
    if metadata.file_type().is_symlink()
        || !metadata.file_type().is_file()
        || !path_has_single_link(&expected_path, &metadata)
    {
        return None;
    }
    Some(expected_path)
}

fn is_safe_asset_component(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
}

fn is_exact_filename(value: &str) -> bool {
    if value.is_empty() || value == "." || value == ".." {
        return false;
    }
    let path = FsPath::new(value);
    path.file_name().and_then(|name| name.to_str()) == Some(value)
}

fn is_real_directory(path: &FsPath) -> bool {
    std::fs::symlink_metadata(path)
        .map(|metadata| !metadata.file_type().is_symlink() && metadata.file_type().is_dir())
        .unwrap_or(false)
}

fn open_validated_attachment_file(base_dir: &FsPath, path: &FsPath) -> Option<std::fs::File> {
    let file = std::fs::File::open(path).ok()?;
    if !managed_parent_directories_are_real(base_dir, path) {
        return None;
    }
    let opened_metadata = file.metadata().ok()?;
    let path_metadata = std::fs::symlink_metadata(path).ok()?;
    if path_metadata.file_type().is_symlink()
        || !path_metadata.file_type().is_file()
        || !opened_metadata.file_type().is_file()
        || !opened_file_has_single_link(&file, &opened_metadata)
        || !opened_file_matches_path(&file, path, &opened_metadata, &path_metadata)
    {
        return None;
    }
    Some(file)
}

fn managed_parent_directories_are_real(base_dir: &FsPath, path: &FsPath) -> bool {
    let Ok(canonical_base) = std::fs::canonicalize(base_dir) else {
        return false;
    };
    let Some(mut current) = path.parent() else {
        return false;
    };
    while current != canonical_base {
        if !current.starts_with(&canonical_base) || !is_real_directory(current) {
            return false;
        }
        let Some(parent) = current.parent() else {
            return false;
        };
        current = parent;
    }
    is_real_directory(&canonical_base)
}

#[cfg(unix)]
fn path_has_single_link(_path: &FsPath, metadata: &std::fs::Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;
    metadata.nlink() == 1
}

#[cfg(windows)]
fn path_has_single_link(path: &FsPath, _metadata: &std::fs::Metadata) -> bool {
    std::fs::File::open(path)
        .ok()
        .and_then(|file| windows_file_identity(&file))
        .map(|identity| identity.number_of_links == 1)
        .unwrap_or(false)
}

#[cfg(not(any(unix, windows)))]
fn path_has_single_link(_path: &FsPath, metadata: &std::fs::Metadata) -> bool {
    metadata.is_file()
}

#[cfg(unix)]
fn opened_file_has_single_link(_file: &std::fs::File, metadata: &std::fs::Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;
    metadata.nlink() == 1
}

#[cfg(windows)]
fn opened_file_has_single_link(file: &std::fs::File, _metadata: &std::fs::Metadata) -> bool {
    windows_file_identity(file)
        .map(|identity| identity.number_of_links == 1)
        .unwrap_or(false)
}

#[cfg(not(any(unix, windows)))]
fn opened_file_has_single_link(_file: &std::fs::File, metadata: &std::fs::Metadata) -> bool {
    metadata.is_file()
}

#[cfg(unix)]
fn opened_file_matches_path(
    _file: &std::fs::File,
    _path: &FsPath,
    left: &std::fs::Metadata,
    right: &std::fs::Metadata,
) -> bool {
    use std::os::unix::fs::MetadataExt;
    left.dev() == right.dev() && left.ino() == right.ino()
}

#[cfg(windows)]
fn opened_file_matches_path(
    file: &std::fs::File,
    path: &FsPath,
    _left: &std::fs::Metadata,
    _right: &std::fs::Metadata,
) -> bool {
    let Some(opened_identity) = windows_file_identity(file) else {
        return false;
    };
    let Some(path_identity) = std::fs::File::open(path)
        .ok()
        .and_then(|path_file| windows_file_identity(&path_file))
    else {
        return false;
    };
    opened_identity.same_file_as(path_identity)
}

#[cfg(not(any(unix, windows)))]
fn opened_file_matches_path(
    _file: &std::fs::File,
    _path: &FsPath,
    left: &std::fs::Metadata,
    right: &std::fs::Metadata,
) -> bool {
    left.len() == right.len()
        && left.modified().ok() == right.modified().ok()
        && left.created().ok() == right.created().ok()
}

#[cfg(windows)]
#[derive(Clone, Copy)]
struct WindowsFileIdentity {
    volume_serial_number: u32,
    file_index: u64,
    number_of_links: u32,
}

#[cfg(windows)]
impl WindowsFileIdentity {
    fn same_file_as(self, other: Self) -> bool {
        self.volume_serial_number == other.volume_serial_number
            && self.file_index == other.file_index
    }
}

#[cfg(windows)]
fn windows_file_identity(file: &std::fs::File) -> Option<WindowsFileIdentity> {
    use std::mem::MaybeUninit;
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::{
        GetFileInformationByHandle, BY_HANDLE_FILE_INFORMATION,
    };

    let mut information = MaybeUninit::<BY_HANDLE_FILE_INFORMATION>::zeroed();
    // SAFETY: `File` owns a valid handle for this call and `information` points
    // to writable storage for the complete Windows result structure.
    let succeeded =
        unsafe { GetFileInformationByHandle(file.as_raw_handle() as _, information.as_mut_ptr()) };
    if succeeded == 0 {
        return None;
    }
    // SAFETY: A nonzero return value guarantees that Windows initialized the
    // complete result structure.
    let information = unsafe { information.assume_init() };
    Some(WindowsFileIdentity {
        volume_serial_number: information.dwVolumeSerialNumber,
        file_index: ((information.nFileIndexHigh as u64) << 32) | information.nFileIndexLow as u64,
        number_of_links: information.nNumberOfLinks,
    })
}

fn sanitize_header_filename(value: &str) -> String {
    value.replace('\\', "_").replace('"', "_")
}

#[cfg(test)]
mod tests {
    use super::{build_attachment_response, parse_byte_range, AttachmentMetadata, FsPath};
    use http_body_util::BodyExt;
    use std::fs;

    #[test]
    fn attachment_path_requires_exact_managed_identity() {
        use super::resolve_managed_attachment_path;

        let temp_root = std::env::temp_dir().join(format!(
            "magi-attachment-traversal-{}",
            uuid::Uuid::new_v4()
        ));
        let attachment_dir = temp_root.join("data/resources/chat/files/session-1/turn-1");
        fs::create_dir_all(&attachment_dir).unwrap();
        let attachment_file = attachment_dir.join("att-1__notes.txt");
        fs::write(&attachment_file, b"ok").unwrap();
        let exact_relative =
            FsPath::new("data/resources/chat/files/session-1/turn-1/att-1__notes.txt");

        assert_eq!(
            resolve_managed_attachment_path(
                &temp_root,
                "session-1",
                "turn-1",
                "att-1",
                "text_file",
                "notes.txt",
                exact_relative.to_str().unwrap(),
            ),
            Some(std::fs::canonicalize(&attachment_file).unwrap())
        );

        let polluted = temp_root.join("private.txt");
        fs::write(&polluted, b"private").unwrap();
        assert!(resolve_managed_attachment_path(
            &temp_root,
            "session-1",
            "turn-1",
            "att-1",
            "text_file",
            "notes.txt",
            "private.txt",
        )
        .is_none());

        let hard_link = attachment_dir.join("second-link");
        fs::hard_link(&attachment_file, &hard_link).unwrap();
        assert!(resolve_managed_attachment_path(
            &temp_root,
            "session-1",
            "turn-1",
            "att-1",
            "text_file",
            "notes.txt",
            exact_relative.to_str().unwrap(),
        )
        .is_none());
        fs::remove_file(hard_link).unwrap();

        fs::remove_file(&attachment_file).unwrap();
        if create_file_symlink(&polluted, &attachment_file) {
            assert!(resolve_managed_attachment_path(
                &temp_root,
                "session-1",
                "turn-1",
                "att-1",
                "text_file",
                "notes.txt",
                exact_relative.to_str().unwrap(),
            )
            .is_none());
        }
        let _ = fs::remove_file(&attachment_file);
        let _ = fs::remove_dir_all(&attachment_dir);
        let polluted_dir = temp_root.join("polluted-turn");
        fs::create_dir_all(&polluted_dir).unwrap();
        fs::write(polluted_dir.join("att-1__notes.txt"), b"private").unwrap();
        if create_directory_symlink(&polluted_dir, &attachment_dir) {
            assert!(resolve_managed_attachment_path(
                &temp_root,
                "session-1",
                "turn-1",
                "att-1",
                "text_file",
                "notes.txt",
                exact_relative.to_str().unwrap(),
            )
            .is_none());
        }

        let _ = fs::remove_dir_all(&temp_root);
    }

    #[test]
    fn opened_file_identity_matches_only_current_path() {
        use super::opened_file_matches_path;

        let temp_root =
            std::env::temp_dir().join(format!("magi-file-identity-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&temp_root).unwrap();
        let expected_path = temp_root.join("expected.txt");
        let other_path = temp_root.join("other.txt");
        fs::write(&expected_path, b"expected").unwrap();
        fs::write(&other_path, b"other").unwrap();

        let opened = fs::File::open(&expected_path).unwrap();
        let opened_metadata = opened.metadata().unwrap();
        let expected_metadata = fs::symlink_metadata(&expected_path).unwrap();
        assert!(opened_file_matches_path(
            &opened,
            &expected_path,
            &opened_metadata,
            &expected_metadata,
        ));

        let other_metadata = fs::symlink_metadata(&other_path).unwrap();
        assert!(!opened_file_matches_path(
            &opened,
            &other_path,
            &opened_metadata,
            &other_metadata,
        ));

        let _ = fs::remove_dir_all(&temp_root);
    }

    #[tokio::test]
    async fn attachment_response_streams_large_file_in_bounded_chunks() {
        let temp_root =
            std::env::temp_dir().join(format!("magi-attachment-stream-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&temp_root).unwrap();
        let file_path = temp_root.join("large.bin");
        let payload = vec![b'x'; 2 * 1024 * 1024 + 17];
        fs::write(&file_path, &payload).unwrap();
        let response = build_attachment_response(
            AttachmentMetadata {
                mime_type: "application/octet-stream".to_string(),
                original_name: "large.bin".to_string(),
                absolute_path: file_path.clone(),
            },
            fs::File::open(&file_path).unwrap(),
            None,
        )
        .unwrap();
        assert_eq!(
            response.headers().get("content-length").unwrap(),
            payload.len().to_string().as_str()
        );

        let mut body = response.into_body();
        let mut chunks = Vec::new();
        while let Some(frame) = body.frame().await {
            let frame = frame.unwrap();
            if let Ok(data) = frame.into_data() {
                chunks.push(data);
            }
        }

        assert!(chunks.len() >= 3);
        assert!(chunks.iter().all(|chunk| chunk.len() <= 1024 * 1024));
        assert_eq!(
            chunks
                .iter()
                .flat_map(|chunk| chunk.iter().copied())
                .collect::<Vec<_>>(),
            payload
        );
        let _ = fs::remove_dir_all(&temp_root);
    }

    #[test]
    fn byte_ranges_are_bounded_and_unsatisfiable_ranges_are_rejected() {
        assert_eq!(parse_byte_range("bytes=0-6", 14), Ok(Some((0, 6))));
        assert_eq!(parse_byte_range("bytes=7-", 14), Ok(Some((7, 13))));
        assert_eq!(parse_byte_range("bytes=-4", 14), Ok(Some((10, 13))));
        assert_eq!(parse_byte_range("items=0-1", 14), Ok(None));
        assert_eq!(parse_byte_range("bytes=14-", 14), Err(()));
        assert_eq!(parse_byte_range("bytes=0-1,4-5", 14), Err(()));
    }

    #[cfg(unix)]
    fn create_file_symlink(source: &FsPath, target: &FsPath) -> bool {
        std::os::unix::fs::symlink(source, target).is_ok()
    }

    #[cfg(windows)]
    fn create_file_symlink(source: &FsPath, target: &FsPath) -> bool {
        std::os::windows::fs::symlink_file(source, target).is_ok()
    }

    #[cfg(unix)]
    fn create_directory_symlink(source: &FsPath, target: &FsPath) -> bool {
        std::os::unix::fs::symlink(source, target).is_ok()
    }

    #[cfg(windows)]
    fn create_directory_symlink(source: &FsPath, target: &FsPath) -> bool {
        std::os::windows::fs::symlink_dir(source, target).is_ok()
    }
}
