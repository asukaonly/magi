// Hide the console window in release builds on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod connections;
mod desktop_log_history;
mod desktop_presence;
mod dmg_cleanup;
mod downloads;
mod external_url;
mod service_host;

use connections::{protocol::CenterClient, Profile};
use magi_server_runtime::config::ServerConfig;
use serde::Serialize;
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::thread;
use tauri::{AppHandle, Manager, State};

const DESKTOP_LOG_MAX_BYTES: u64 = 50 * 1024 * 1024;

#[derive(Default)]
struct BackendState {
    generation: std::sync::atomic::AtomicU64,
    runtime: Mutex<Option<ActiveConnection>>,
    operation: tokio::sync::Mutex<()>,
    last_log: Mutex<Option<PathBuf>>,
}

struct ActiveConnection {
    service: Option<service_host::LocalService>,
    response: StartBackendResponse,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct StartBackendResponse {
    ok: bool,
    base_url: String,
    session_token: String,
    server_id: String,
    profile_id: String,
    mode: String,
    data_epoch: String,
    content_epoch: String,
    expires_at_ms: Option<i64>,
    api_pid: Option<u32>,
    runtime_worker_pid: Option<u32>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PollStartupResponse {
    ready: bool,
    phase: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendStartupDiagnosticsResponse {
    log_path: Option<String>,
    log_excerpt: Option<String>,
    log_read_error: Option<String>,
}

fn stop_backend_inner(state: &BackendState) -> Result<(), String> {
    let previous = {
        let mut runtime = state
            .runtime
            .lock()
            .map_err(|_| "Service state lock failed")?;
        state
            .generation
            .fetch_add(1, std::sync::atomic::Ordering::AcqRel);
        runtime.take()
    };
    // Dropping a local service closes its owner pipe and waits for its children.
    drop(previous);
    Ok(())
}

async fn reuse_local_connection(
    state: &BackendState,
    profile_id: &str,
) -> Result<Option<StartBackendResponse>, String> {
    let snapshot = {
        let mut runtime = state
            .runtime
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
        .runtime
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
async fn start_backend(
    app: AppHandle,
    state: State<'_, BackendState>,
    connections: State<'_, connections::Connections>,
) -> Result<StartBackendResponse, String> {
    let _operation = state.operation.lock().await;
    let profile_id = connections
        .list()
        .active_profile_id
        .ok_or("Select a connection first")?;
    if let Some(response) = reuse_local_connection(&state, &profile_id).await? {
        return Ok(response);
    }
    stop_backend_inner(&state)?;
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
    let response = StartBackendResponse {
        ok: true,
        base_url,
        session_token: token,
        server_id: info.server_id,
        profile_id,
        mode: mode.into(),
        data_epoch: info.maintenance.data_epoch,
        content_epoch: info.maintenance.content_epoch,
        expires_at_ms: expiry,
        api_pid: service.as_ref().map(service_host::LocalService::pid),
        runtime_worker_pid: None,
    };
    *state
        .runtime
        .lock()
        .map_err(|_| "Service state lock failed")? = Some(ActiveConnection {
        service,
        response: response.clone(),
    });
    Ok(response)
}

#[tauri::command]
async fn poll_backend_startup(
    state: State<'_, BackendState>,
) -> Result<PollStartupResponse, String> {
    let _operation = state.operation.lock().await;
    let response = {
        let mut runtime = state
            .runtime
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
        ready: info.runtime_ready || maintenance,
        phase: if maintenance {
            "recovering_maintenance"
        } else if info.runtime_ready {
            "ready"
        } else {
            "waiting_for_worker"
        }
        .into(),
    })
}

#[tauri::command]
async fn stop_backend(state: State<'_, BackendState>) -> Result<serde_json::Value, String> {
    let _operation = state.operation.lock().await;
    stop_backend_inner(&state)?;
    Ok(serde_json::json!({"ok":true}))
}

#[tauri::command]
fn backend_status(state: State<'_, BackendState>) -> serde_json::Value {
    let mut runtime = state.runtime.lock().unwrap_or_else(|e| e.into_inner());
    let running = runtime.as_mut().is_some_and(|active| {
        active
            .service
            .as_mut()
            .is_none_or(|service| service.running().unwrap_or(false))
    });
    serde_json::json!({"running":running,"baseUrl":runtime.as_ref().map(|active| &active.response.base_url)})
}

#[tauri::command]
fn get_backend_base_url(state: State<'_, BackendState>) -> serde_json::Value {
    serde_json::json!({"baseUrl":state.runtime.lock().unwrap_or_else(|e| e.into_inner()).as_ref().map(|active| &active.response.base_url)})
}

#[tauri::command]
fn read_backend_startup_diagnostics(
    state: State<'_, BackendState>,
) -> BackendStartupDiagnosticsResponse {
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
    BackendStartupDiagnosticsResponse {
        log_path: log_path.map(|path| path.display().to_string()),
        log_excerpt: excerpt
            .as_ref()
            .and_then(|result| result.as_ref().ok())
            .cloned(),
        log_read_error: excerpt.and_then(Result::err),
    }
}

#[tauri::command]
fn list_connection_profiles(connections: State<'_, connections::Connections>) -> serde_json::Value {
    serde_json::json!({"state":connections.list(),"supports_remote":cfg!(any(target_os = "macos", windows))})
}

#[tauri::command]
async fn pair_center(
    connections: State<'_, connections::Connections>,
    address: String,
    pairing_token: String,
    name: String,
) -> Result<Profile, String> {
    connections.pair(address, pairing_token, name).await
}

#[tauri::command]
async fn select_connection_profile(
    connections: State<'_, connections::Connections>,
    backend: State<'_, BackendState>,
    profile_id: String,
) -> Result<(), String> {
    let _operation = backend.operation.lock().await;
    connections.profile(&profile_id)?;
    stop_backend_inner(&backend)?;
    connections.activate(profile_id).await
}

#[tauri::command]
async fn forget_connection_profile(
    connections: State<'_, connections::Connections>,
    backend: State<'_, BackendState>,
    profile_id: String,
) -> Result<(), String> {
    let _operation = backend.operation.lock().await;
    if profile_id == "local" {
        return Err("The local connection cannot be removed".into());
    }
    if connections.list().active_profile_id.as_deref() == Some(&profile_id) {
        stop_backend_inner(&backend)?;
    }
    connections.forget(profile_id).await
}

#[tauri::command]
async fn renew_center_session(
    connections: State<'_, connections::Connections>,
    backend: State<'_, BackendState>,
    profile_id: String,
) -> Result<connections::AccessSession, String> {
    let _operation = backend.operation.lock().await;
    if connections.list().active_profile_id.as_deref() != Some(&profile_id) {
        return Err("Connection is no longer active".into());
    }
    let session = connections.renew(profile_id.clone()).await?;
    if let Some(active) = backend
        .runtime
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

#[tauri::command]
fn set_close_to_tray_enabled(
    state: State<'_, desktop_presence::DesktopPresenceState>,
    enabled: bool,
) -> Result<(), String> {
    state.set_close_to_tray_enabled(enabled)
}

#[tauri::command]
fn set_start_minimized(
    state: State<'_, desktop_presence::DesktopPresenceState>,
    enabled: bool,
) -> Result<(), String> {
    state.set_start_minimized(enabled)
}

#[tauri::command]
fn set_skip_quit_confirmation(
    state: State<'_, desktop_presence::DesktopPresenceState>,
    enabled: bool,
) -> Result<(), String> {
    state.set_skip_quit_confirmation(enabled)
}

#[tauri::command]
fn set_onboarding_completed(
    state: State<'_, desktop_presence::DesktopPresenceState>,
    completed: bool,
) -> Result<(), String> {
    state.set_onboarding_completed(completed)
}

#[tauri::command]
fn apply_start_minimized(
    app: AppHandle,
    state: State<'_, desktop_presence::DesktopPresenceState>,
) -> Result<(), String> {
    if state.should_start_minimized()? {
        desktop_presence::hide_main_window(&app)?;
    }
    Ok(())
}

#[tauri::command]
fn confirm_exit_app(app: AppHandle) -> Result<(), String> {
    exit_after_backend_stop(app);
    Ok(())
}

#[tauri::command]
fn cancel_exit_request() -> Result<(), String> {
    Ok(())
}

/// Open an approved external URL using the operating system's default handler.
#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    external_url::open(&url)
}

#[tauri::command]
fn clear_desktop_log_history(
    state: State<'_, desktop_log_history::DesktopLogRuntime>,
) -> Result<desktop_log_history::DesktopLogClearResult, String> {
    Ok(state.clear())
}

#[cfg(windows)]
mod dwm_caption {
    use std::ffi::c_void;

    pub const DWMWA_BORDER_COLOR: u32 = 34;
    pub const DWMWA_CAPTION_COLOR: u32 = 35;
    pub const DWMWA_TEXT_COLOR: u32 = 36;

    #[link(name = "dwmapi")]
    unsafe extern "system" {
        pub fn DwmSetWindowAttribute(
            hwnd: *mut c_void,
            attribute: u32,
            pv_attribute: *const c_void,
            cb_attribute: u32,
        ) -> i32;
    }
}

#[cfg(windows)]
fn apply_caption_color(window: &tauri::WebviewWindow, r: u8, g: u8, b: u8) -> Result<(), String> {
    use std::ffi::c_void;

    let raw = window.hwnd().map_err(|e| format!("hwnd: {e}"))?;
    let hwnd: *mut c_void = raw.0 as *mut c_void;

    let caption: u32 = ((b as u32) << 16) | ((g as u32) << 8) | (r as u32);
    // Relative luminance to pick legible caption text color.
    let lum = 0.299 * (r as f32) + 0.587 * (g as f32) + 0.114 * (b as f32);
    let text: u32 = if lum >= 140.0 { 0x00202020 } else { 0x00E8E8E8 };

    unsafe {
        let size = std::mem::size_of::<u32>() as u32;
        dwm_caption::DwmSetWindowAttribute(
            hwnd,
            dwm_caption::DWMWA_CAPTION_COLOR,
            &caption as *const _ as *const c_void,
            size,
        );
        dwm_caption::DwmSetWindowAttribute(
            hwnd,
            dwm_caption::DWMWA_TEXT_COLOR,
            &text as *const _ as *const c_void,
            size,
        );
        dwm_caption::DwmSetWindowAttribute(
            hwnd,
            dwm_caption::DWMWA_BORDER_COLOR,
            &caption as *const _ as *const c_void,
            size,
        );
    }
    Ok(())
}

#[tauri::command]
fn set_window_caption_color(
    window: tauri::WebviewWindow,
    r: u8,
    g: u8,
    b: u8,
) -> Result<(), String> {
    #[cfg(windows)]
    {
        return apply_caption_color(&window, r, g, b);
    }
    #[cfg(not(windows))]
    {
        let _ = (window, r, g, b);
        Ok(())
    }
}

fn stop_backend_for_app_exit(app: &AppHandle) {
    let state: State<'_, BackendState> = app.state();
    if let Err(err) = stop_backend_inner(&state) {
        log::warn!("Failed to stop backend during app exit: {err}");
    }
}

fn hide_main_window_for_exit(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if let Err(err) = window.hide() {
            log::warn!("Failed to hide main window during app exit: {err}");
        }
    }
}

fn exit_after_backend_stop(app: AppHandle) {
    hide_main_window_for_exit(&app);
    thread::spawn(move || {
        let state: State<'_, BackendState> = app.state();
        if let Err(err) = stop_backend_inner(&state) {
            log::warn!("Failed to stop backend during confirmed app exit: {err}");
        }
        app.exit(0);
    });
}

#[cfg(not(target_os = "macos"))]
fn disable_native_window_decorations(app: &AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        log::warn!("Main window not found while disabling native decorations");
        return;
    };
    if let Err(err) = window.set_decorations(false) {
        log::warn!("Failed to disable native window decorations: {err}");
    }
}

fn main() {
    let log_level = if cfg!(debug_assertions) {
        log::LevelFilter::Debug
    } else {
        log::LevelFilter::Info
    };
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::new().skip_logger().build())
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            let _ = desktop_presence::restore_main_window(app);
        }))
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .manage(BackendState::default())
        .manage(desktop_presence::DesktopPresenceState::default())
        .setup(move |app| {
            let client_directory = app.path().app_config_dir()?;
            magi_platform::private_data::protect_magi_data_root(&client_directory).map_err(std::io::Error::other)?;
            let log_directory = app.path().app_log_dir()?;
            magi_platform::private_data::protect_magi_data_root(&log_directory).map_err(std::io::Error::other)?;
            app.manage(desktop_log_history::DesktopLogRuntime::install(log_directory, DESKTOP_LOG_MAX_BYTES, log_level).map_err(std::io::Error::other)?);
            let connection_directory = app.path().app_config_dir()?.join("connections");
            app.manage(connections::Connections::open(&connection_directory).map_err(std::io::Error::other)?);
            let current_version = app.package_info().version.to_string();
            log::info!(
                "Magi desktop setup starting (version={current_version}, log_level={log_level:?})"
            );
            log::info!("tauri updater plugin enabled for desktop runtime");

            #[cfg(target_os = "macos")]
            dmg_cleanup::detach_installer_volume_after_launch();

            if let Err(err) = desktop_presence::setup(app.handle()) {
                log::warn!(
                    "Optional desktop presence setup is unavailable; continuing without tray integration: {err}"
                );
            }

            #[cfg(not(target_os = "macos"))]
            disable_native_window_decorations(app.handle());

            Ok(())
        })
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { api, .. } => {
                let state: State<'_, desktop_presence::DesktopPresenceState> = window.state();
                match state.close_action() {
                    Ok(desktop_presence::CloseAction::HideToTray) => {
                        api.prevent_close();
                        let _ = desktop_presence::hide_main_window(window.app_handle());
                    }
                    Ok(desktop_presence::CloseAction::QuitImmediately) => {
                        api.prevent_close();
                        exit_after_backend_stop(window.app_handle().clone());
                    }
                    Ok(desktop_presence::CloseAction::RequestQuitConfirmation) => {
                        api.prevent_close();
                        let _ = desktop_presence::emit_quit_requested(window.app_handle());
                    }
                    Err(_) => {}
                }
            }
            tauri::WindowEvent::Destroyed => {
                let state: State<'_, BackendState> = window.state();
                let _ = stop_backend_inner(&state);
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            downloads::download_portability_file,
            list_connection_profiles,
            pair_center,
            select_connection_profile,
            forget_connection_profile,
            renew_center_session,
            start_backend,
            poll_backend_startup,
            stop_backend,
            backend_status,
            get_backend_base_url,
            read_backend_startup_diagnostics,
            set_close_to_tray_enabled,
            set_start_minimized,
            set_skip_quit_confirmation,
            set_onboarding_completed,
            apply_start_minimized,
            confirm_exit_app,
            cancel_exit_request,
            open_url,
            clear_desktop_log_history,
            set_window_caption_color
        ])
        .build(tauri::generate_context!())
        .expect("failed to build Magi desktop application");

    app.run(|app_handle, event| match event {
        tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
            hide_main_window_for_exit(app_handle);
            stop_backend_for_app_exit(app_handle);
        }
        _ => {}
    });
}

#[cfg(test)]
mod connection_reuse_tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

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
            let body = serde_json::json!({"success":true,"data":{"server_id":"center","protocol_version":1,"runtime_ready":true,"maintenance":{"data_epoch":"new-epoch","content_epoch":"content","phase":"completed"}}}).to_string();
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", body.len(), body).as_bytes()).await.unwrap();
        });
        let state = BackendState::default();
        *state.runtime.lock().unwrap() = Some(ActiveConnection {
            service: None,
            response: StartBackendResponse {
                ok: true,
                base_url: format!("http://{address}/api"),
                session_token: "owner-access".into(),
                server_id: "center".into(),
                profile_id: "local".into(),
                mode: "local".into(),
                data_epoch: "old-epoch".into(),
                content_epoch: "content".into(),
                expires_at_ms: None,
                api_pid: Some(123),
                runtime_worker_pid: None,
            },
        });
        let response = reuse_local_connection(&state, "local")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(response.data_epoch, "new-epoch");
        assert_eq!(response.api_pid, Some(123));
        assert_eq!(
            state
                .runtime
                .lock()
                .unwrap()
                .as_ref()
                .unwrap()
                .response
                .data_epoch,
            "new-epoch"
        );
        assert_eq!(
            state.generation.load(std::sync::atomic::Ordering::Acquire),
            0
        );
        server.await.unwrap();
    }
}
