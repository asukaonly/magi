//! Desktop connection lifecycle and native commands; service implementation lives in the server.

use super::{protocol::CenterClient, Profile};
use crate::{connections, service_host};
use magi_service_contract::config::ServerConfig;
use serde::Serialize;
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};

#[derive(Default)]
pub struct ConnectionRuntime {
    generation: AtomicU64,
    active: Mutex<Option<ActiveConnection>>,
    operation: tokio::sync::Mutex<()>,
    last_log: Mutex<Option<PathBuf>>,
}

struct ActiveConnection {
    service: Option<service_host::LocalService>,
    response: ConnectionInfo,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionInfo {
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
    ready: bool,
    phase: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionStartupDiagnostics {
    log_path: Option<String>,
    log_excerpt: Option<String>,
    log_read_error: Option<String>,
}

impl ConnectionRuntime {
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
        if let Some(service) = active.service.as_mut() {
            if !service.running()? {
                return Ok(None);
            }
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
    if active.response.profile_id != profile_id {
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
    let profile_id = connections
        .list()
        .active_profile_id
        .ok_or("Select a connection first")?;
    if let Some(response) = reuse_local_connection(&state, &profile_id).await? {
        return Ok(response);
    }
    state.disconnect()?;
    let profile = connections.profile(&profile_id)?;
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
    *state
        .active
        .lock()
        .map_err(|_| "Service state lock failed")? = Some(ActiveConnection {
        service,
        response: response.clone(),
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
    let client = if response.mode == "local" {
        CenterClient::local(&response.base_url)?
    } else {
        CenterClient::remote(&response.base_url)?
    };
    let info = client.info(&response.session_token).await?;
    if info.server_id != response.server_id {
        return Err("Center identity changed".into());
    }
    let maintenance = !matches!(info.maintenance.phase.as_str(), "idle" | "completed");
    Ok(PollStartupResponse {
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
    serde_json::json!({"state":connections.list(),"supports_remote":cfg!(any(target_os = "macos", windows))})
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
    profile_id: String,
) -> Result<(), String> {
    let _operation = state.operation.lock().await;
    if profile_id == "local" {
        return Err("The local connection cannot be removed".into());
    }
    if connections.list().active_profile_id.as_deref() == Some(&profile_id) {
        state.disconnect()?;
    }
    connections.forget(profile_id).await
}

#[tauri::command]
pub async fn renew_center_session(
    connections: State<'_, connections::Connections>,
    state: State<'_, ConnectionRuntime>,
    profile_id: String,
) -> Result<connections::AccessSession, String> {
    let _operation = state.operation.lock().await;
    if connections.list().active_profile_id.as_deref() != Some(&profile_id) {
        return Err("Connection is no longer active".into());
    }
    let session = connections.renew(profile_id.clone()).await?;
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

    fn connection_info(mode: &str) -> ConnectionInfo {
        ConnectionInfo {
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
            service: None,
            response: connection_info("remote"),
        });
        assert!(!state.is_current(generation));
        assert!(state.is_current(state.snapshot().unwrap().0));
    }

    #[tokio::test]
    async fn local_reuse_refreshes_data_epoch_without_replacing_the_connection() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
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
            service: None,
            response: ConnectionInfo {
                ok: true,
                base_url: format!("http://{address}/api"),
                session_token: "owner-access".into(),
                server_id: "center".into(),
                profile_id: "local".into(),
                mode: "local".into(),
                data_epoch: "old-epoch".into(),
                content_epoch: "content".into(),
                expires_at_ms: None,
                local_service_pid: Some(123),
            },
        });
        let response = reuse_local_connection(&state, "local")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(response.data_epoch, "new-epoch");
        assert_eq!(response.local_service_pid, Some(123));
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
    }
}
