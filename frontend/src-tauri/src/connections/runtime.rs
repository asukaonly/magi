//! Desktop connection lifecycle and native commands; service implementation lives in the server.

use super::{protocol::CenterClient, Profile};
use crate::{connections, service_host};
use magi_service_contract::config::ServerConfig;
use serde::Serialize;
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};

mod recovery;
pub use recovery::start_monitor;

#[derive(Default)]
pub struct ConnectionRuntime {
    generation: AtomicU64,
    shutting_down: AtomicBool,
    active: Mutex<Option<ActiveConnection>>,
    pub(crate) operation: tokio::sync::Mutex<()>,
    last_log: Mutex<Option<PathBuf>>,
}

struct ActiveConnection {
    service: Option<service_host::LocalService>,
    response: ConnectionInfo,
    recovery: recovery::RecoverySchedule,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionInfo {
    pub(crate) connection_generation: u64,
    pub(crate) ok: bool,
    pub(crate) base_url: String,
    pub(crate) session_token: String,
    pub(crate) server_id: String,
    pub(crate) profile_id: String,
    pub(crate) mode: String,
    pub(crate) data_epoch: String,
    pub(crate) content_epoch: String,
    pub(crate) expires_at_ms: Option<i64>,
    pub(crate) local_service_pid: Option<u32>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PollStartupResponse {
    connection_generation: u64,
    ready: bool,
    phase: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionSnapshot {
    generation: u64,
    profile_id: String,
    mode: String,
    recovering: bool,
}

/// A credential-free snapshot, readable even while connection operations wait.
#[tauri::command]
pub fn read_connection_snapshot(
    state: State<'_, ConnectionRuntime>,
) -> Result<Option<ConnectionSnapshot>, String> {
    state.connection_snapshot()
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionStartupDiagnostics {
    log_path: Option<String>,
    log_excerpt: Option<String>,
    log_read_error: Option<String>,
}

impl ConnectionRuntime {
    fn connection_snapshot(&self) -> Result<Option<ConnectionSnapshot>, String> {
        let active = self
            .active
            .lock()
            .map_err(|_| "Connection state unavailable")?;
        Ok(active.as_ref().map(|active| ConnectionSnapshot {
            generation: self.generation.load(Ordering::Acquire),
            profile_id: active.response.profile_id.clone(),
            mode: active.response.mode.clone(),
            recovering: active.response.mode == "local" && active.service.is_none(),
        }))
    }
    pub fn shutdown(&self) -> Result<(), String> {
        self.shutting_down.store(true, Ordering::Release);
        self.disconnect()
    }

    pub fn snapshot(&self) -> Result<(u64, ConnectionInfo), String> {
        let active = self
            .active
            .lock()
            .map_err(|_| "Connection state unavailable")?;
        let info = active
            .as_ref()
            .ok_or("Connect to a center first")?
            .response
            .clone();
        Ok((self.generation.load(Ordering::Acquire), info))
    }

    pub fn is_current(&self, generation: u64) -> bool {
        self.generation.load(Ordering::Acquire) == generation
    }

    /// Invalidate client work before releasing the owned local service, if any.
    pub fn disconnect(&self) -> Result<(), String> {
        let previous = {
            let mut active = self
                .active
                .lock()
                .map_err(|_| "Connection state unavailable")?;
            self.generation.fetch_add(1, Ordering::AcqRel);
            if let Some(active) = active.as_ref() {
                active.recovery.cancelled.store(true, Ordering::Release);
            }
            active.take()
        };
        // Dropping a local service closes its owner pipe and waits for its children.
        // A remote connection owns no service process and needs no shutdown request.
        drop(previous);
        Ok(())
    }
}

async fn reuse_local_connection(
    state: &ConnectionRuntime,
    profile_id: &str,
) -> Result<Option<ConnectionInfo>, String> {
    let generation = state.generation.load(Ordering::Acquire);
    let snapshot = {
        let mut runtime = state
            .active
            .lock()
            .map_err(|_| "Service state lock failed")?;
        let Some(active) = runtime.as_mut() else {
            return Ok(None);
        };
        if active.response.mode != "local" || active.response.profile_id != profile_id {
            return Ok(None);
        }
        let Some(service) = active.service.as_mut() else {
            return Err("Local service recovery is in progress".into());
        };
        if !service.running()? {
            return Ok(None);
        }
        active.response.clone()
    };
    let info = CenterClient::local(&snapshot.base_url)?
        .info(&snapshot.session_token)
        .await?;
    if info.server_id != snapshot.server_id {
        return Err("Center identity changed".into());
    }
    let mut response = snapshot;
    response.data_epoch = info.maintenance.data_epoch;
    response.content_epoch = info.maintenance.content_epoch;
    let mut runtime = state
        .active
        .lock()
        .map_err(|_| "Service state lock failed")?;
    let active = runtime.as_mut().ok_or("Local service disconnected")?;
    if !state.is_current(generation) || active.response.profile_id != profile_id {
        return Err("Connection changed".into());
    }
    active.response = response.clone();
    Ok(Some(response))
}

#[tauri::command]
pub async fn connect_active_profile(
    app: AppHandle,
    state: State<'_, ConnectionRuntime>,
    connections: State<'_, connections::Connections>,
) -> Result<ConnectionInfo, String> {
    let _operation = state.operation.lock().await;
    if state.shutting_down.load(Ordering::Acquire) {
        return Err("Desktop is stopping".into());
    }
    let profile_id = connections
        .list()
        .active_profile_id
        .ok_or("Select a connection first")?;
    let previous_generation = state.generation.load(Ordering::Acquire);
    drop(_operation);
    if let Some(response) = reuse_local_connection(&state, &profile_id).await? {
        return Ok(response);
    }
    let operation = state.operation.lock().await;
    if !state.is_current(previous_generation)
        || connections.list().active_profile_id.as_deref() != Some(&profile_id)
    {
        return Err("Connection changed during startup".into());
    }
    state.disconnect()?;
    let generation = state.generation.load(Ordering::Acquire);
    let profile = connections.profile(&profile_id)?;
    drop(operation);
    let (service, base_url, token, expiry, mode, expected_id) = match profile {
        Profile::Local { .. } => {
            let data = service_host::local_data_root()?;
            let (binary, mut config) = if cfg!(debug_assertions) {
                let project = Path::new(env!("CARGO_MANIFEST_DIR"))
                    .parent()
                    .and_then(Path::parent)
                    .ok_or("Project directory is unavailable")?;
                (
                    project.join(if cfg!(windows) {
                        "target/debug/magi-server.exe"
                    } else {
                        "target/debug/magi-server"
                    }),
                    ServerConfig::for_development(project, data),
                )
            } else {
                let bundle = app
                    .path()
                    .resource_dir()
                    .map_err(|e| e.to_string())?
                    .join("server-dist");
                (
                    bundle.join(if cfg!(windows) {
                        "magi-server.exe"
                    } else {
                        "magi-server"
                    }),
                    ServerConfig::for_bundle(&bundle, data),
                )
            };
            config.port = 0;
            let config_path = app
                .path()
                .app_config_dir()
                .map_err(|e| e.to_string())?
                .join("local-server.json");
            let log_path = app
                .path()
                .app_log_dir()
                .map_err(|e| e.to_string())?
                .join("service.log");
            *state
                .last_log
                .lock()
                .map_err(|_| "Service diagnostics lock failed")? = Some(log_path.clone());
            let service = tokio::task::spawn_blocking(move || {
                service_host::LocalService::start(&binary, &config, &config_path, log_path)
            })
            .await
            .map_err(|_| "Service launch failed")??;
            let base = service.base_url.clone();
            let token = service.session_token.clone();
            (Some(service), base, token, None, "local", None)
        }
        Profile::Remote {
            api_base_url,
            server_id,
            ..
        } => {
            *state
                .last_log
                .lock()
                .map_err(|_| "Service diagnostics lock failed")? = None;
            let session = connections.renew(profile_id.clone()).await?;
            (
                None,
                api_base_url,
                session.access_token,
                Some(session.expires_at_ms),
                "remote",
                Some(server_id),
            )
        }
    };
    let client = if mode == "local" {
        CenterClient::local(&base_url)?
    } else {
        CenterClient::remote(&base_url)?
    };
    let info = client.info(&token).await?;
    if expected_id.as_ref().is_some_and(|id| *id != info.server_id) {
        return Err("Center identity changed".into());
    }
    let response = ConnectionInfo {
        connection_generation: generation,
        ok: true,
        base_url,
        session_token: token,
        server_id: info.server_id,
        profile_id,
        mode: mode.into(),
        data_epoch: info.maintenance.data_epoch,
        content_epoch: info.maintenance.content_epoch,
        expires_at_ms: expiry,
        local_service_pid: service.as_ref().map(service_host::LocalService::pid),
    };
    let _operation = state.operation.lock().await;
    if !state.is_current(generation)
        || connections.list().active_profile_id.as_deref() != Some(&response.profile_id)
    {
        return Err("Connection changed during startup".into());
    }
    let mut active = state
        .active
        .lock()
        .map_err(|_| "Service state lock failed")?;
    if state.shutting_down.load(Ordering::Acquire) {
        return Err("Desktop is stopping".into());
    }
    *active = Some(ActiveConnection {
        service,
        response: response.clone(),
        recovery: Default::default(),
    });
    Ok(response)
}

#[tauri::command]
pub async fn poll_connection_startup(
    state: State<'_, ConnectionRuntime>,
) -> Result<PollStartupResponse, String> {
    let _operation = state.operation.lock().await;
    let response = {
        let mut runtime = state
            .active
            .lock()
            .map_err(|_| "Service state lock failed")?;
        let active = runtime.as_mut().ok_or("Service is not connected")?;
        if let Some(service) = active.service.as_mut() {
            if !service.running()? {
                return Err("Local service exited; inspect startup diagnostics".into());
            }
        }
        active.response.clone()
    };
    drop(_operation);
    let client = if response.mode == "local" {
        CenterClient::local(&response.base_url)?
    } else {
        CenterClient::remote(&response.base_url)?
    };
    let info = client.info(&response.session_token).await?;
    if !state.is_current(response.connection_generation) {
        return Ok(PollStartupResponse {
            ready: false,
            phase: "connecting".into(),
            connection_generation: state.generation.load(Ordering::Acquire),
        });
    }
    if info.server_id != response.server_id {
        return Err("Center identity changed".into());
    }
    let maintenance = !matches!(info.maintenance.phase.as_str(), "idle" | "completed");
    Ok(PollStartupResponse {
        connection_generation: response.connection_generation,
        ready: info.service_ready || maintenance,
        phase: if maintenance {
            "recovering_maintenance"
        } else if info.service_ready {
            "ready"
        } else {
            "waiting_for_worker"
        }
        .into(),
    })
}

#[tauri::command]
pub async fn disconnect_service(
    state: State<'_, ConnectionRuntime>,
) -> Result<serde_json::Value, String> {
    let _operation = state.operation.lock().await;
    state.disconnect()?;
    Ok(serde_json::json!({"ok":true}))
}

#[tauri::command]
pub fn read_connection_startup_diagnostics(
    state: State<'_, ConnectionRuntime>,
) -> ConnectionStartupDiagnostics {
    let log_path = state
        .last_log
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .clone();
    let excerpt = log_path.as_ref().map(|path| {
        let mut file = fs::File::open(path).map_err(|e| e.to_string())?;
        let length = file.metadata().map_err(|e| e.to_string())?.len();
        file.seek(SeekFrom::Start(length.saturating_sub(65536)))
            .map_err(|e| e.to_string())?;
        let mut bytes = Vec::new();
        file.take(65536)
            .read_to_end(&mut bytes)
            .map_err(|e| e.to_string())?;
        Ok::<String, String>(String::from_utf8_lossy(&bytes).into_owned())
    });
    ConnectionStartupDiagnostics {
        log_path: log_path.map(|path| path.display().to_string()),
        log_excerpt: excerpt
            .as_ref()
            .and_then(|result| result.as_ref().ok())
            .cloned(),
        log_read_error: excerpt.and_then(Result::err),
    }
}

#[tauri::command]
pub fn list_connection_profiles(
    connections: State<'_, connections::Connections>,
) -> serde_json::Value {
    serde_json::json!({"state":connections.list(),"supports_remote":cfg!(any(unix, windows))})
}

#[tauri::command]
pub async fn pair_center(
    connections: State<'_, connections::Connections>,
    address: String,
    pairing_token: String,
    name: String,
    device_name: String,
) -> Result<Profile, String> {
    connections
        .pair(address, pairing_token, name, device_name)
        .await
}

#[tauri::command]
pub async fn select_connection_profile(
    connections: State<'_, connections::Connections>,
    state: State<'_, ConnectionRuntime>,
    profile_id: String,
) -> Result<(), String> {
    let _operation = state.operation.lock().await;
    connections.profile(&profile_id)?;
    state.disconnect()?;
    connections.activate(profile_id).await
}

#[tauri::command]
pub async fn forget_connection_profile(
    connections: State<'_, connections::Connections>,
    state: State<'_, ConnectionRuntime>,
    delivery: State<'_, crate::background_delivery::DeliveryRuntime>,
    profile_id: String,
    discard_pending: bool,
) -> Result<(), String> {
    let _operation = state.operation.lock().await;
    if profile_id == "local" {
        return Err("The local connection cannot be removed".into());
    }
    connections.profile(&profile_id)?;
    let queued_profile = profile_id.clone();
    let queue = delivery
        .storage(move |queue| queue.profile_status(&queued_profile))
        .await?;
    require_discard_confirmation(&queue, discard_pending)?;
    if connections.list().active_profile_id.as_deref() == Some(&profile_id) {
        state.disconnect()?;
    }
    let queue_profile = profile_id.clone();
    delivery
        .storage(move |queue| queue.forget(&queue_profile))
        .await?;
    connections.forget(profile_id).await
}

fn require_discard_confirmation(
    queue: &magi_delivery::QueueStatus,
    confirmed: bool,
) -> Result<(), String> {
    if queue.pending + queue.failed > 0 && !confirmed {
        return Err("connection_has_pending_data".into());
    }
    Ok(())
}

#[tauri::command]
pub async fn connection_profile_queue(
    connections: State<'_, connections::Connections>,
    delivery: State<'_, crate::background_delivery::DeliveryRuntime>,
    profile_id: String,
) -> Result<magi_delivery::QueueStatus, String> {
    connections.profile(&profile_id)?;
    delivery
        .storage(move |queue| queue.profile_status(&profile_id))
        .await
}

#[tauri::command]
pub async fn repair_connection_profile(
    connections: State<'_, connections::Connections>,
    state: State<'_, ConnectionRuntime>,
    delivery: State<'_, crate::background_delivery::DeliveryRuntime>,
    profile_id: String,
    address: String,
    name: String,
    pairing_token: Option<String>,
    device_name: String,
    discard_pending: bool,
) -> Result<Profile, String> {
    let generation = state.generation.load(Ordering::Acquire);
    let replaces_authorization = pairing_token.is_some();
    if replaces_authorization {
        let id = profile_id.clone();
        let queue = delivery
            .storage(move |queue| queue.profile_status(&id))
            .await?;
        require_discard_confirmation(&queue, discard_pending)?;
    }
    let repair = connections
        .prepare_repair(
            profile_id.clone(),
            address,
            name,
            pairing_token,
            device_name,
        )
        .await?;
    let _operation = state.operation.lock().await;
    if !state.is_current(generation) {
        return Err("Connection changed during repair".into());
    }
    if replaces_authorization {
        let id = profile_id.clone();
        let queue = delivery
            .storage(move |queue| queue.profile_status(&id))
            .await?;
        require_discard_confirmation(&queue, discard_pending)?;
    }
    connections.validate_repair(&repair)?;
    // A new authorization owns a different producer identity. Never silently replay
    // old records as that identity, even when both connect to the same center.
    if connections.list().active_profile_id.as_deref() == Some(&profile_id) {
        state.disconnect()?;
    }
    if replaces_authorization {
        let id = profile_id.clone();
        delivery.storage(move |queue| queue.forget(&id)).await?;
    }
    connections.apply_repair(repair).await
}

#[tauri::command]
pub async fn renew_center_session(
    connections: State<'_, connections::Connections>,
    state: State<'_, ConnectionRuntime>,
    profile_id: String,
) -> Result<connections::AccessSession, String> {
    renew_session(&connections, &state, profile_id).await
}

async fn renew_session(
    connections: &connections::Connections,
    state: &ConnectionRuntime,
    profile_id: String,
) -> Result<connections::AccessSession, String> {
    let _operation = state.operation.lock().await;
    if connections.list().active_profile_id.as_deref() != Some(&profile_id) {
        return Err("Connection is no longer active".into());
    }
    let generation = state.generation.load(Ordering::Acquire);
    drop(_operation);
    let session = connections.renew(profile_id.clone()).await?;
    let _operation = state.operation.lock().await;
    if !state.is_current(generation)
        || connections.list().active_profile_id.as_deref() != Some(&profile_id)
    {
        return Err("Connection changed during session renewal".into());
    }
    if let Some(active) = state
        .active
        .lock()
        .map_err(|_| "Service state lock failed")?
        .as_mut()
    {
        if active.response.profile_id != profile_id {
            return Err("Connection changed during session renewal".into());
        }
        active.response.session_token = session.access_token.clone();
        active.response.expires_at_ms = Some(session.expires_at_ms);
    }
    Ok(session)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    pub(super) fn connection_info(mode: &str) -> ConnectionInfo {
        ConnectionInfo {
            connection_generation: 0,
            ok: true,
            base_url: "https://remote.example/api".into(),
            session_token: "test-session".into(),
            server_id: "center".into(),
            profile_id: mode.into(),
            mode: mode.into(),
            data_epoch: "data".into(),
            content_epoch: "content".into(),
            expires_at_ms: Some(1),
            local_service_pid: None,
        }
    }

    #[test]
    fn destructive_profile_actions_require_explicit_pending_data_consent() {
        let empty = magi_delivery::QueueStatus::default();
        assert!(require_discard_confirmation(&empty, false).is_ok());
        let queued = magi_delivery::QueueStatus {
            pending: 1,
            failed: 2,
            ..Default::default()
        };
        assert_eq!(
            require_discard_confirmation(&queued, false).unwrap_err(),
            "connection_has_pending_data"
        );
        assert!(require_discard_confirmation(&queued, true).is_ok());
    }

    #[tokio::test]
    async fn stalled_renewal_does_not_block_switch_or_offline_storage() {
        use std::time::Duration;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let root = tempfile::tempdir().unwrap();
        let connections = connections::Connections::open(root.path()).unwrap();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = format!("http://{}/api", listener.local_addr().unwrap());
        let id = uuid::Uuid::new_v4().to_string();
        let mut response = connection_info("remote");
        response.profile_id = id.clone();
        response.server_id = uuid::Uuid::new_v4().to_string();
        response.base_url = address.clone();
        let client_id = uuid::Uuid::new_v4().to_string();
        {
            let mut store = connections.store.lock().unwrap();
            let mut data = store.data.clone();
            data.profiles.push(Profile::Remote {
                id: id.clone(),
                name: "Test".into(),
                api_base_url: address,
                server_id: response.server_id.clone(),
                client_id: client_id.clone(),
            });
            data.active_profile_id = Some(id.clone());
            store.save(data).unwrap();
        }
        connections.credentials.put(&id, &"a".repeat(64)).unwrap();
        let state = ConnectionRuntime::default();
        *state.active.lock().unwrap() = Some(ActiveConnection {
            service: None,
            response: response.clone(),
            recovery: Default::default(),
        });
        let (started_tx, started_rx) = tokio::sync::oneshot::channel();
        let (release_tx, release_rx) = tokio::sync::oneshot::channel();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buffer = [0; 8192];
            socket.read(&mut buffer).await.unwrap();
            started_tx.send(()).unwrap();
            release_rx.await.unwrap();
            let body = serde_json::json!({"success": true,"data":{"server_id":response.server_id,"client_id":client_id,"access_token":"b".repeat(64),"expires_at_ms":i64::MAX}}).to_string();
            socket
                .write_all(
                    format!(
                        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                        body.len()
                    )
                    .as_bytes(),
                )
                .await
                .unwrap();
            let (mut socket, _) = listener.accept().await.unwrap();
            socket.read(&mut buffer).await.unwrap();
            let body = serde_json::json!({"success":true,"data":{"server_id":response.server_id,"protocol_version":magi_service_contract::SERVER_PROTOCOL_VERSION,"service_ready":true,"maintenance":{"phase":"idle","data_epoch":"data","content_epoch":"content"}}}).to_string();
            socket
                .write_all(
                    format!(
                        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                        body.len()
                    )
                    .as_bytes(),
                )
                .await
                .unwrap();
        });
        let renewal = renew_session(&connections, &state, id);
        let switch = async {
            started_rx.await.unwrap();
            let operation =
                tokio::time::timeout(Duration::from_millis(250), state.operation.lock())
                    .await
                    .expect("network I/O must not hold the runtime lock");
            state.disconnect().unwrap();
            tokio::time::timeout(
                Duration::from_millis(250),
                connections.activate("local".into()),
            )
            .await
            .expect("network I/O must not hold the profile lock")
            .unwrap();
            drop(operation);
            release_tx.send(()).unwrap();
        };
        let (result, ()) = tokio::join!(renewal, switch);
        assert_eq!(
            result.err().unwrap(),
            "Connection changed during session renewal"
        );
        assert!(state.snapshot().is_err());
        assert_eq!(
            connections.list().active_profile_id.as_deref(),
            Some("local")
        );
        server.await.unwrap();
    }

    #[tokio::test]
    async fn empty_desktop_state_does_not_own_or_reuse_a_service() {
        let state = ConnectionRuntime::default();
        assert!(state.snapshot().is_err());
        assert!(reuse_local_connection(&state, "local")
            .await
            .unwrap()
            .is_none());
        assert!(state.last_log.lock().unwrap().is_none());
        state.disconnect().unwrap();
        assert!(state.snapshot().is_err());
    }

    #[tokio::test]
    async fn disconnecting_remote_invalidates_client_work_without_a_service_process() {
        let state = ConnectionRuntime::default();
        *state.active.lock().unwrap() = Some(ActiveConnection {
            recovery: Default::default(),
            service: None,
            response: connection_info("remote"),
        });
        assert!(reuse_local_connection(&state, "remote")
            .await
            .unwrap()
            .is_none());
        let (generation, info) = state.snapshot().unwrap();
        assert!(info.local_service_pid.is_none());
        assert!(state.is_current(generation));
        state.disconnect().unwrap();
        assert!(!state.is_current(generation));
        assert!(state.snapshot().is_err());
        // Reconnecting the same profile must not revive work from the old connection.
        *state.active.lock().unwrap() = Some(ActiveConnection {
            recovery: Default::default(),
            service: None,
            response: connection_info("remote"),
        });
        assert!(!state.is_current(generation));
        assert!(state.is_current(state.snapshot().unwrap().0));
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn local_reuse_refreshes_data_epoch_without_replacing_the_connection() {
        use std::os::unix::fs::PermissionsExt;
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let root = std::env::temp_dir().join(format!("magi-reuse-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        let binary = root.join("service");
        fs::write(&binary, format!("#!/bin/sh\nread bootstrap\nprintf '{{\"baseUrl\":\"http://{address}/api\",\"serverPid\":%s}}\\n' \"$$\"\nwhile IFS= read -r line; do :; done\n")).unwrap();
        fs::set_permissions(&binary, fs::Permissions::from_mode(0o700)).unwrap();
        let service = service_host::LocalService::start(
            &binary,
            &ServerConfig::for_development(&root, root.join("data")),
            &root.join("config.json"),
            root.join("service.log"),
        )
        .unwrap();
        let pid = service.pid();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut request = [0; 4096];
            let length = socket.read(&mut request).await.unwrap();
            assert!(
                String::from_utf8_lossy(&request[..length]).starts_with("GET /api/server/info ")
            );
            let body = serde_json::json!({"success":true,"data":{"server_id":"center","protocol_version":2,"service_ready":true,"maintenance":{"data_epoch":"new-epoch","content_epoch":"content","phase":"completed"}}}).to_string();
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", body.len(), body).as_bytes()).await.unwrap();
        });
        let state = ConnectionRuntime::default();
        *state.active.lock().unwrap() = Some(ActiveConnection {
            recovery: Default::default(),
            service: Some(service),
            response: ConnectionInfo {
                connection_generation: 0,
                ok: true,
                base_url: format!("http://{address}/api"),
                session_token: "owner-access".into(),
                server_id: "center".into(),
                profile_id: "local".into(),
                mode: "local".into(),
                data_epoch: "old-epoch".into(),
                content_epoch: "content".into(),
                expires_at_ms: None,
                local_service_pid: Some(pid),
            },
        });
        let response = reuse_local_connection(&state, "local")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(response.data_epoch, "new-epoch");
        assert_eq!(response.local_service_pid, Some(pid));
        assert_eq!(
            state
                .active
                .lock()
                .unwrap()
                .as_ref()
                .unwrap()
                .response
                .data_epoch,
            "new-epoch"
        );
        assert_eq!(state.generation.load(Ordering::Acquire), 0);
        server.await.unwrap();
        state.shutdown().unwrap();
        fs::remove_dir_all(root).unwrap();
    }
}
