//! Bounded center downloads saved atomically through a device-native save dialog.
use std::io::Write;
use std::sync::atomic::Ordering;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use base64::Engine;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use tauri::{AppHandle, State};
use tauri_plugin_dialog::DialogExt;

use crate::{connections, BackendState, StartBackendResponse};
use connections::protocol::CenterClient;

const CHUNK_BYTES: usize = 1024 * 1024;
const MAX_FILE_BYTES: u64 = 2 * 1024 * 1024 * 1024;
static DOWNLOADS: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(2);

#[derive(Deserialize)]
struct Metadata {
    operation_id: String,
    name: String,
    size: u64,
    version: String,
}
#[derive(Deserialize)]
struct Chunk {
    operation_id: String,
    offset: u64,
    version: String,
    data: String,
    sha256: String,
}

fn validate_metadata(metadata: &Metadata, id: &str) -> Result<(), String> {
    if metadata.operation_id != id
        || metadata.size > MAX_FILE_BYTES
        || metadata.name.is_empty()
        || metadata.name.chars().count() > 255
        || metadata
            .name
            .chars()
            .any(|c| c.is_control() || matches!(c, '/' | '\\'))
        || matches!(metadata.name.as_str(), "." | "..")
        || metadata.version.len() != 64
        || !metadata.version.bytes().all(|c| c.is_ascii_hexdigit())
    {
        return Err("Center returned invalid download metadata".into());
    }
    Ok(())
}

fn decode_chunk(chunk: Chunk, metadata: &Metadata, offset: u64) -> Result<Vec<u8>, String> {
    if chunk.operation_id != metadata.operation_id
        || chunk.offset != offset
        || chunk.version != metadata.version
        || chunk.data.len() > CHUNK_BYTES.div_ceil(3) * 4
    {
        return Err("Center returned a different file chunk".into());
    }
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(chunk.data)
        .map_err(|_| "Center file chunk encoding is invalid")?;
    let expected = (metadata.size - offset).min(CHUNK_BYTES as u64) as usize;
    if bytes.len() != expected || format!("{:x}", Sha256::digest(&bytes)) != chunk.sha256 {
        return Err("Center file chunk failed its integrity check".into());
    }
    Ok(bytes)
}

fn ensure_connection(state: &BackendState, generation: u64) -> Result<(), String> {
    if state.generation.load(Ordering::Acquire) != generation {
        return Err("Connection changed during download".into());
    }
    Ok(())
}

async fn refresh_access(
    snapshot: &mut StartBackendResponse,
    connections: &connections::Connections,
) -> Result<(), String> {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "Device clock is invalid")?
        .as_millis() as i64;
    if snapshot.mode == "remote" && snapshot.expires_at_ms.unwrap_or(0) < now + 60_000 {
        let access = connections.renew(snapshot.profile_id.clone()).await?;
        if access.server_id != snapshot.server_id {
            return Err("Center identity changed".into());
        }
        snapshot.session_token = access.access_token;
        snapshot.expires_at_ms = Some(access.expires_at_ms);
    }
    Ok(())
}

#[tauri::command]
pub async fn download_portability_file(
    app: AppHandle,
    state: State<'_, BackendState>,
    connections: State<'_, connections::Connections>,
    operation_id: String,
    profile_id: String,
) -> Result<Option<String>, String> {
    let _permit = DOWNLOADS
        .try_acquire()
        .map_err(|_| "Two downloads are already active")?;
    if uuid::Uuid::parse_str(&operation_id)
        .map_err(|_| "Invalid download operation")?
        .to_string()
        != operation_id
    {
        return Err("Invalid download operation".into());
    }
    let (generation, mut snapshot) = {
        let runtime = state
            .runtime
            .lock()
            .map_err(|_| "Connection state unavailable")?;
        (
            state.generation.load(Ordering::Acquire),
            runtime
                .as_ref()
                .map(|active| active.response.clone())
                .ok_or("Connect to a center first")?,
        )
    };
    if snapshot.profile_id != profile_id {
        return Err("Connection changed before download".into());
    }
    let client = if snapshot.mode == "local" {
        CenterClient::local(&snapshot.base_url)?
    } else {
        CenterClient::remote(&snapshot.base_url)?
    };
    refresh_access(&mut snapshot, &connections).await?;
    ensure_connection(&state, generation)?;
    let path = format!("files/outputs/{operation_id}");
    let metadata: Metadata = client.file_output(&path, &snapshot.session_token).await?;
    validate_metadata(&metadata, &operation_id)?;
    ensure_connection(&state, generation)?;
    let (sender, receiver) = tokio::sync::oneshot::channel();
    app.dialog()
        .file()
        .set_file_name(&metadata.name)
        .save_file(move |selection| {
            let _ = sender.send(selection);
        });
    let Some(destination) = receiver
        .await
        .map_err(|_| "Save dialog closed unexpectedly")?
    else {
        return Ok(None);
    };
    let destination = destination
        .into_path()
        .map_err(|_| "Select a local destination file")?;
    ensure_connection(&state, generation)?;
    let parent = destination
        .parent()
        .ok_or("Destination directory is invalid")?
        .to_path_buf();
    let mut temporary = tokio::task::spawn_blocking(move || {
        tempfile::Builder::new()
            .prefix(".magi-download-")
            .tempfile_in(parent)
    })
    .await
    .map_err(|_| "Download staging failed")?
    .map_err(|_| "Could not create the destination file")?;
    let started = Instant::now();
    let mut offset = 0;
    while offset < metadata.size {
        if started.elapsed() > Duration::from_secs(3600) {
            return Err("Download time limit exceeded".into());
        }
        ensure_connection(&state, generation)?;
        refresh_access(&mut snapshot, &connections).await?;
        ensure_connection(&state, generation)?;
        let chunk: Chunk = client
            .file_output(
                &format!("{path}/chunks?offset={offset}&version={}", metadata.version),
                &snapshot.session_token,
            )
            .await?;
        ensure_connection(&state, generation)?;
        let bytes = decode_chunk(chunk, &metadata, offset)?;
        offset += bytes.len() as u64;
        temporary = tokio::task::spawn_blocking(move || {
            temporary
                .write_all(&bytes)
                .map_err(|_| "Could not write the download")?;
            Ok::<_, String>(temporary)
        })
        .await
        .map_err(|_| "Download write interrupted")??;
    }
    ensure_connection(&state, generation)?;
    // Recheck even empty files, and reject replacement after the final chunk.
    let final_metadata: Metadata = client.file_output(&path, &snapshot.session_token).await?;
    if final_metadata.version != metadata.version || final_metadata.size != metadata.size {
        return Err("Center file changed during download".into());
    }
    ensure_connection(&state, generation)?;
    let saved_path = destination.to_string_lossy().into_owned();
    tokio::task::spawn_blocking(move || finish_download(temporary, &destination, metadata.size))
        .await
        .map_err(|_| "Download save interrupted")??;
    Ok(Some(saved_path))
}

fn finish_download(
    temporary: tempfile::NamedTempFile,
    destination: &std::path::Path,
    size: u64,
) -> Result<(), String> {
    if temporary
        .as_file()
        .metadata()
        .map_err(|_| "Could not inspect the download")?
        .len()
        != size
    {
        return Err("Download is incomplete".into());
    }
    temporary
        .as_file()
        .sync_all()
        .map_err(|_| "Could not sync the download")?;
    temporary
        .persist(destination)
        .map_err(|_| "Could not save the completed download")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn metadata() -> Metadata {
        Metadata {
            operation_id: "id".into(),
            name: "memory.magibackup".into(),
            size: 3,
            version: "a".repeat(64),
        }
    }
    fn chunk() -> Chunk {
        Chunk {
            operation_id: "id".into(),
            offset: 0,
            version: "a".repeat(64),
            data: "YWJj".into(),
            sha256: format!("{:x}", Sha256::digest(b"abc")),
        }
    }
    #[test]
    fn incomplete_download_does_not_replace_an_existing_destination() {
        let root = tempfile::tempdir().unwrap();
        let destination = root.path().join("saved.magibackup");
        std::fs::write(&destination, b"original").unwrap();
        let mut temporary = tempfile::NamedTempFile::new_in(root.path()).unwrap();
        temporary.write_all(b"partial").unwrap();
        assert!(finish_download(temporary, &destination, 100).is_err());
        assert_eq!(std::fs::read(&destination).unwrap(), b"original");
        let mut complete = tempfile::NamedTempFile::new_in(root.path()).unwrap();
        complete.write_all(b"complete").unwrap();
        finish_download(complete, &destination, 8).unwrap();
        assert_eq!(std::fs::read(&destination).unwrap(), b"complete");
        assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 1);
    }
    #[test]
    fn checks_chunk_identity_length_and_checksum_before_writing() {
        assert_eq!(decode_chunk(chunk(), &metadata(), 0).unwrap(), b"abc");
        let mut wrong = chunk();
        wrong.offset = 1;
        assert!(decode_chunk(wrong, &metadata(), 0).is_err());
        let mut wrong = chunk();
        wrong.version = "b".repeat(64);
        assert!(decode_chunk(wrong, &metadata(), 0).is_err());
        let mut wrong = chunk();
        wrong.data = "YWJk".into();
        assert!(decode_chunk(wrong, &metadata(), 0).is_err());
        let mut wrong = chunk();
        wrong.data = "YWI=".into();
        assert!(decode_chunk(wrong, &metadata(), 0).is_err());
    }
    #[test]
    fn center_cannot_supply_destination_paths_or_unbounded_sizes() {
        for name in ["../file", "/tmp/file", "C:\\file", "..", "a\nfile"] {
            let mut value = metadata();
            value.name = name.into();
            assert!(validate_metadata(&value, "id").is_err());
        }
        let mut value = metadata();
        value.size = MAX_FILE_BYTES + 1;
        assert!(validate_metadata(&value, "id").is_err());
    }
}
