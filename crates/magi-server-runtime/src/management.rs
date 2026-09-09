//! Private same-account operator channel. Network location never grants ownership.

use std::path::Path;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, RwLock,
};
use std::time::Duration;

use magi_gateway::auth::AuthStore;
use magi_service_contract::lifecycle::SupervisorStatus;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::{watch, Semaphore};

#[derive(Deserialize, Serialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
pub enum Request {
    Status,
    Pair,
    Clients,
    Revoke { client_id: String },
}

pub struct ManagementServer {
    task: tokio::task::JoinHandle<()>,
    path: std::path::PathBuf,
}

impl ManagementServer {
    /// The caller holds the server instance lease before replacing a stale socket.
    pub fn bind(
        root: &Path,
        auth: Arc<AuthStore>,
        ready: Arc<AtomicBool>,
        supervisor: Arc<RwLock<SupervisorStatus>>,
        base_url: String,
        mut shutdown: watch::Receiver<bool>,
    ) -> Result<Self, String> {
        use std::os::unix::fs::{FileTypeExt, PermissionsExt};
        let path = root.join("runtime/manage.sock");
        if let Ok(metadata) = std::fs::symlink_metadata(&path) {
            if !metadata.file_type().is_socket() {
                return Err("Management path is not a socket".into());
            }
            std::fs::remove_file(&path).map_err(|e| e.to_string())?;
        }
        let listener = UnixListener::bind(&path)
            .map_err(|e| format!("Failed to bind management socket: {e}"))?;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
            .map_err(|e| e.to_string())?;
        let task = tokio::spawn(async move {
            let operations = Arc::new(Semaphore::new(8));
            let mut handlers = tokio::task::JoinSet::new();
            loop {
                tokio::select! {
                    _ = shutdown.changed() => break,
                    Some(_) = handlers.join_next(), if !handlers.is_empty() => {},
                    incoming = listener.accept() => {
                        let Ok((stream, _)) = incoming else { break; };
                        if !same_account(&stream) { continue; }
                        let Ok(permit) = Arc::clone(&operations).try_acquire_owned() else { continue; };
                        let auth = Arc::clone(&auth);
                        let ready = Arc::clone(&ready);
                        let supervisor = Arc::clone(&supervisor);
                        let base_url = base_url.clone();
                        handlers.spawn(async move {
                            let _permit = permit;
                            let _ = tokio::time::timeout(Duration::from_secs(5), serve(stream, auth, ready, supervisor, base_url)).await;
                        });
                    },
                }
            }
            handlers.abort_all();
        });
        Ok(Self { task, path })
    }

    pub async fn wait(&mut self) {
        let _ = (&mut self.task).await;
    }
}

impl Drop for ManagementServer {
    fn drop(&mut self) {
        self.task.abort();
        let _ = std::fs::remove_file(&self.path);
    }
}

fn same_account(stream: &UnixStream) -> bool {
    // SAFETY: geteuid has no preconditions and reads the effective account id.
    stream
        .peer_cred()
        .is_ok_and(|cred| cred.uid() == unsafe { libc::geteuid() })
}

async fn read_line(stream: &mut BufReader<UnixStream>, limit: usize) -> Result<Vec<u8>, String> {
    let mut line = Vec::new();
    loop {
        let buffer = stream.fill_buf().await.map_err(|e| e.to_string())?;
        if buffer.is_empty() {
            return Err("Management channel closed before response".into());
        }
        let length = buffer
            .iter()
            .position(|byte| *byte == b'\n')
            .map(|i| i + 1)
            .unwrap_or(buffer.len());
        if line.len() + length > limit {
            return Err("Management message exceeds size limit".into());
        }
        line.extend_from_slice(&buffer[..length]);
        stream.consume(length);
        if line.last() == Some(&b'\n') {
            return Ok(line);
        }
    }
}

async fn serve(
    stream: UnixStream,
    auth: Arc<AuthStore>,
    ready: Arc<AtomicBool>,
    supervisor: Arc<RwLock<SupervisorStatus>>,
    base_url: String,
) -> Result<(), String> {
    let mut stream = BufReader::new(stream);
    let request: Request =
        serde_json::from_slice(&read_line(&mut stream, 4096).await?).map_err(|e| e.to_string())?;
    let result = tokio::task::spawn_blocking(move || -> Result<Value, String> {
        match request {
            Request::Status => Ok(json!({"server_id": auth.server_id, "protocol_version": magi_service_contract::SERVER_PROTOCOL_VERSION,
                "base_url": base_url, "service_ready": ready.load(Ordering::Acquire),
                "supervisor": supervisor.read().unwrap_or_else(|e| e.into_inner()).clone()})),
            Request::Pair => {
                serde_json::to_value(auth.create_pairing_grant()?).map_err(|e| e.to_string())
            }
            Request::Clients => serde_json::to_value(auth.clients()?).map_err(|e| e.to_string()),
            Request::Revoke { client_id } => {
                auth.revoke(&client_id)?;
                Ok(Value::Null)
            }
        }
    })
    .await
    .map_err(|e| e.to_string())?;
    let response = match result {
        Ok(data) => json!({"success": true, "data": data}),
        Err(error) => json!({"success": false, "message": error}),
    };
    let mut bytes = serde_json::to_vec(&response).map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    stream.write_all(&bytes).await.map_err(|e| e.to_string())
}

pub async fn request(root: &Path, request: Request) -> Result<Value, String> {
    tokio::time::timeout(Duration::from_secs(6), async {
        let stream = UnixStream::connect(root.join("runtime/manage.sock"))
            .await
            .map_err(|e| format!("Cannot connect to running service: {e}"))?;
        if !same_account(&stream) {
            return Err("Management channel belongs to another account".into());
        }
        let mut stream = BufReader::new(stream);
        let mut bytes = serde_json::to_vec(&request).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        stream.write_all(&bytes).await.map_err(|e| e.to_string())?;
        let response: Value = serde_json::from_slice(&read_line(&mut stream, 65536).await?)
            .map_err(|e| e.to_string())?;
        if response["success"] != true {
            return Err(response["message"]
                .as_str()
                .unwrap_or("Management request failed")
                .into());
        }
        Ok(response["data"].clone())
    })
    .await
    .map_err(|_| "Management request timed out".to_owned())?
}
