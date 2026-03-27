mod desktop_presence;

#[cfg(unix)]
use libc::{kill, SIGTERM};
use serde::Serialize;
use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

const BACKEND_HOST: &str = "127.0.0.1";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(25);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(3);
const SHUTDOWN_POLL_INTERVAL: Duration = Duration::from_millis(100);
const MAX_ERROR_LINES: usize = 20;

#[derive(Default)]
struct BackendState {
    runtime: Mutex<BackendRuntime>,
    recent_errors: Arc<Mutex<Vec<String>>>,
}

#[derive(Default)]
struct BackendRuntime {
    api_process: Option<BackendProcess>,
    runtime_worker_process: Option<BackendProcess>,
    base_url: Option<String>,
    ws_base_url: Option<String>,
    session_token: Option<String>,
    api_pid: Option<u32>,
    runtime_worker_pid: Option<u32>,
}

struct ExternalBackendConfig {
    host: String,
    port: u16,
    base_url: String,
    ws_base_url: String,
    session_token: String,
}

enum BackendProcess {
    Sidecar(Option<CommandChild>),
    Dev(Option<Child>),
}

impl BackendProcess {
    fn kill(&mut self) {
        match self {
            Self::Sidecar(child) => {
                if let Some(sidecar) = child.take() {
                    let _ = sidecar.kill();
                }
            }
            Self::Dev(child) => {
                if let Some(process) = child.as_mut() {
                    let _ = process.kill();
                }
                child.take();
            }
        }
    }

    fn wait_for_exit(&mut self, timeout: Duration) -> bool {
        match self {
            Self::Sidecar(_) => false,
            Self::Dev(child) => {
                let start = Instant::now();
                while start.elapsed() < timeout {
                    if let Some(process) = child.as_mut() {
                        match process.try_wait() {
                            Ok(Some(_)) => {
                                child.take();
                                return true;
                            }
                            Ok(None) => thread::sleep(SHUTDOWN_POLL_INTERVAL),
                            Err(_) => break,
                        }
                    } else {
                        return true;
                    }
                }
                false
            }
        }
    }
}

struct ManagedBackendStart {
    api_process: BackendProcess,
    runtime_worker_process: BackendProcess,
    api_pid: Option<u32>,
    runtime_worker_pid: Option<u32>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct StartBackendResponse {
    ok: bool,
    base_url: String,
    ws_base_url: String,
    session_token: String,
    api_pid: Option<u32>,
    runtime_worker_pid: Option<u32>,
    error: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendStatusResponse {
    running: bool,
    base_url: Option<String>,
    ws_base_url: Option<String>,
    api_pid: Option<u32>,
    runtime_worker_pid: Option<u32>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct StopBackendResponse {
    ok: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendBaseUrlResponse {
    base_url: Option<String>,
}

fn pick_open_port() -> Result<u16, String> {
    let listener = TcpListener::bind((BACKEND_HOST, 0))
        .map_err(|err| format!("Failed to pick free backend port: {err}"))?;
    let port = listener
        .local_addr()
        .map_err(|err| format!("Failed to read backend port: {err}"))?
        .port();
    drop(listener);
    Ok(port)
}

fn wait_for_health(host: &str, port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if let Ok(mut stream) = TcpStream::connect((host, port)) {
            let request = format!(
                "GET /api/health HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n\r\n",
                host, port
            );
            if stream.write_all(request.as_bytes()).is_ok() {
                let mut response = String::new();
                if stream.read_to_string(&mut response).is_ok()
                    && (response.starts_with("HTTP/1.1 200")
                        || response.starts_with("HTTP/1.0 200"))
                {
                    return true;
                }
            }
        }
        thread::sleep(Duration::from_millis(200));
    }
    false
}

fn wait_for_port_close(host: &str, port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if TcpStream::connect((host, port)).is_err() {
            return true;
        }
        thread::sleep(SHUTDOWN_POLL_INTERVAL);
    }
    false
}

#[cfg(unix)]
fn send_termination_signal(pid: u32) -> bool {
    unsafe { kill(pid as i32, SIGTERM) == 0 }
}

#[cfg(not(unix))]
fn send_termination_signal(_pid: u32) -> bool {
    false
}

#[cfg(unix)]
fn is_pid_running(pid: u32) -> bool {
    let result = unsafe { kill(pid as i32, 0) };
    if result == 0 {
        return true;
    }

    std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
}

#[cfg(not(unix))]
fn is_pid_running(_pid: u32) -> bool {
    false
}

fn wait_for_pid_exit(pid: u32, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if !is_pid_running(pid) {
            return true;
        }
        thread::sleep(SHUTDOWN_POLL_INTERVAL);
    }
    !is_pid_running(pid)
}

fn wait_for_process_stop(
    process: &mut BackendProcess,
    pid: Option<u32>,
    timeout: Duration,
) -> bool {
    #[cfg(unix)]
    if let Some(pid) = pid {
        return wait_for_pid_exit(pid, timeout);
    }
    let _ = pid;
    process.wait_for_exit(timeout)
}

fn request_runtime_shutdown(host: &str, port: u16, session_token: &str) -> bool {
    let Ok(mut stream) = TcpStream::connect((host, port)) else {
        return false;
    };

    let body = "{}";
    let mut request = format!(
        "POST /api/runtime/shutdown HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: {}\r\n",
        host,
        port,
        body.len()
    );
    if !session_token.trim().is_empty() {
        request.push_str(&format!("X-Magi-Session-Token: {}\r\n", session_token));
    }
    request.push_str("\r\n");
    request.push_str(body);

    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }

    response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
}

fn extract_backend_endpoint(base_url: &str) -> Option<(String, u16)> {
    let without_scheme = base_url
        .strip_prefix("http://")
        .or_else(|| base_url.strip_prefix("https://"))?;
    let authority = without_scheme.split('/').next()?;
    let (host, port_text) = authority.rsplit_once(':')?;
    let port = port_text.parse::<u16>().ok()?;
    Some((host.to_string(), port))
}

fn generate_session_token() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    format!("magi-desktop-{}-{}", std::process::id(), nanos)
}

fn env_bool(name: &str) -> bool {
    env::var(name)
        .map(|value| {
            matches!(
                value.trim().to_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(false)
}

fn parse_external_backend_config() -> Result<Option<ExternalBackendConfig>, String> {
    if !env_bool("MAGI_TAURI_EXTERNAL_BACKEND") {
        return Ok(None);
    }

    let host =
        env::var("MAGI_TAURI_EXTERNAL_BACKEND_HOST").unwrap_or_else(|_| BACKEND_HOST.to_string());
    let port = env::var("MAGI_TAURI_EXTERNAL_BACKEND_PORT")
        .ok()
        .and_then(|text| text.parse::<u16>().ok())
        .unwrap_or(8000);
    let base_url = env::var("MAGI_TAURI_EXTERNAL_BACKEND_API_BASE")
        .unwrap_or_else(|_| format!("http://{}:{}/api", host, port));
    let ws_base_url = env::var("MAGI_TAURI_EXTERNAL_BACKEND_WS_BASE")
        .unwrap_or_else(|_| format!("ws://{}:{}", host, port));
    let session_token = env::var("MAGI_DESKTOP_SESSION_TOKEN").unwrap_or_default();

    Ok(Some(ExternalBackendConfig {
        host,
        port,
        base_url,
        ws_base_url,
        session_token,
    }))
}

fn spawn_sidecar_role(
    app: &AppHandle,
    role: &str,
    port: Option<u16>,
    session_token: &str,
    recent_errors: Arc<Mutex<Vec<String>>>,
) -> Result<(BackendProcess, Option<u32>), String> {
    let mut args = vec![
        "--role".to_string(),
        role.to_string(),
        "--no-reload".to_string(),
    ];
    if role == "api" {
        let port_text = port
            .ok_or_else(|| "API role requires a port".to_string())?
            .to_string();
        args.extend([
            "--host".to_string(),
            BACKEND_HOST.to_string(),
            "--port".to_string(),
            port_text,
        ]);
    }
    let (mut rx, child) = app
        .shell()
        .sidecar("magi-backend")
        .map_err(|err| format!("Failed to prepare backend sidecar: {err}"))?
        .args(args)
        .env("MAGI_DESKTOP_MODE", "1")
        .env("MAGI_DESKTOP_SESSION_TOKEN", session_token)
        .spawn()
        .map_err(|err| format!("Failed to spawn backend sidecar: {err}"))?;

    let pid = child.pid();
    let app_handle = app.clone();
    let role_label = role.to_string();
    let errors_clone = recent_errors.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let message = String::from_utf8_lossy(&line).to_string();
                    let _ = app_handle.emit(
                        "backend-log",
                        format!("{} stdout: {}", role_label, message.trim_end()),
                    );
                }
                CommandEvent::Stderr(line) => {
                    let message = String::from_utf8_lossy(&line).to_string();
                    let _ = app_handle.emit(
                        "backend-log",
                        format!("{} stderr: {}", role_label, message.trim_end()),
                    );
                    if let Ok(mut errors) = errors_clone.lock() {
                        if errors.len() >= MAX_ERROR_LINES {
                            errors.remove(0);
                        }
                        errors.push(format!("{}: {}", role_label, message.trim_end()));
                    }
                }
                CommandEvent::Terminated(payload) => {
                    let _ = app_handle.emit(
                        "backend-exit",
                        format!(
                            "{} exited (code: {:?}, signal: {:?})",
                            role_label, payload.code, payload.signal
                        ),
                    );
                    break;
                }
                _ => {}
            }
        }
    });

    Ok((BackendProcess::Sidecar(Some(child)), Some(pid)))
}

fn find_backend_dir() -> Result<PathBuf, String> {
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let frontend_dir = manifest_dir
        .parent()
        .ok_or_else(|| "Cannot resolve frontend directory".to_string())?;
    let project_root = frontend_dir
        .parent()
        .ok_or_else(|| "Cannot resolve project root directory".to_string())?;
    let backend_dir = project_root.join("backend");
    if backend_dir.exists() {
        Ok(backend_dir)
    } else {
        Err("Backend directory not found for desktop dev fallback".to_string())
    }
}

fn spawn_dev_backend_role(
    role: &str,
    port: Option<u16>,
    session_token: &str,
) -> Result<(BackendProcess, Option<u32>), String> {
    let backend_dir = find_backend_dir()?;

    let mut command = Command::new("python");
    command
        .arg("run_server.py")
        .arg("--role")
        .arg(role)
        .arg("--no-reload")
        .env("MAGI_DESKTOP_MODE", "1")
        .env("MAGI_DESKTOP_SESSION_TOKEN", session_token)
        .current_dir(backend_dir)
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    if role == "api" {
        let port_text = port
            .ok_or_else(|| "API role requires a port".to_string())?
            .to_string();
        command
            .arg("--host")
            .arg(BACKEND_HOST)
            .arg("--port")
            .arg(&port_text);
    }

    let child = command
        .spawn()
        .map_err(|err| format!("Failed to spawn backend with python fallback: {err}"))?;
    let pid = Some(child.id());
    Ok((BackendProcess::Dev(Some(child)), pid))
}

fn spawn_sidecar_backend(
    app: &AppHandle,
    port: u16,
    session_token: &str,
    recent_errors: Arc<Mutex<Vec<String>>>,
) -> Result<ManagedBackendStart, String> {
    let (runtime_worker_process, runtime_worker_pid) = spawn_sidecar_role(
        app,
        "runtime_worker",
        None,
        session_token,
        recent_errors.clone(),
    )?;
    let (api_process, api_pid) =
        match spawn_sidecar_role(app, "api", Some(port), session_token, recent_errors) {
            Ok(result) => result,
            Err(err) => {
                let mut process = runtime_worker_process;
                process.kill();
                return Err(err);
            }
        };

    Ok(ManagedBackendStart {
        api_process,
        runtime_worker_process,
        api_pid,
        runtime_worker_pid,
    })
}

fn spawn_dev_backend_pair(port: u16, session_token: &str) -> Result<ManagedBackendStart, String> {
    let (runtime_worker_process, runtime_worker_pid) =
        spawn_dev_backend_role("runtime_worker", None, session_token)?;
    let (api_process, api_pid) = match spawn_dev_backend_role("api", Some(port), session_token) {
        Ok(result) => result,
        Err(err) => {
            let mut process = runtime_worker_process;
            process.kill();
            return Err(err);
        }
    };

    Ok(ManagedBackendStart {
        api_process,
        runtime_worker_process,
        api_pid,
        runtime_worker_pid,
    })
}

fn stop_backend_inner(state: &BackendState) -> Result<(), String> {
    let mut runtime = state
        .runtime
        .lock()
        .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
    let base_url = runtime.base_url.clone();
    let session_token = runtime.session_token.clone().unwrap_or_default();
    let api_pid = runtime.api_pid;
    let runtime_worker_pid = runtime.runtime_worker_pid;
    if let Some(mut process) = runtime.api_process.take() {
        if let Some(base_url) = base_url.as_deref() {
            if let Some((host, port)) = extract_backend_endpoint(base_url) {
                if request_runtime_shutdown(&host, port, &session_token) {
                    let exited = wait_for_process_stop(&mut process, api_pid, SHUTDOWN_TIMEOUT)
                        || wait_for_port_close(&host, port, SHUTDOWN_TIMEOUT);
                    if !exited {
                        process.kill();
                    }
                } else {
                    if let Some(pid) = api_pid {
                        let _ = send_termination_signal(pid);
                        if !wait_for_process_stop(&mut process, api_pid, SHUTDOWN_TIMEOUT) {
                            process.kill();
                        }
                    } else {
                        process.kill();
                    }
                }
            } else {
                process.kill();
            }
        } else {
            process.kill();
        }
    }
    if let Some(mut process) = runtime.runtime_worker_process.take() {
        if let Some(pid) = runtime_worker_pid {
            let _ = send_termination_signal(pid);
            if !wait_for_process_stop(&mut process, runtime_worker_pid, SHUTDOWN_TIMEOUT) {
                process.kill();
            }
        } else {
            process.kill();
        }
    }
    runtime.base_url = None;
    runtime.ws_base_url = None;
    runtime.session_token = None;
    runtime.api_pid = None;
    runtime.runtime_worker_pid = None;
    Ok(())
}

#[tauri::command]
fn start_backend(
    app: AppHandle,
    state: State<'_, BackendState>,
) -> Result<StartBackendResponse, String> {
    // Clear previous error logs
    if let Ok(mut errors) = state.recent_errors.lock() {
        errors.clear();
    }

    {
        let runtime = state
            .runtime
            .lock()
            .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
        if runtime.base_url.is_some() {
            let base_url = runtime
                .base_url
                .clone()
                .ok_or_else(|| "Backend runtime is missing base URL".to_string())?;
            let ws_base_url = runtime
                .ws_base_url
                .clone()
                .ok_or_else(|| "Backend runtime is missing websocket URL".to_string())?;
            let session_token = runtime
                .session_token
                .clone()
                .ok_or_else(|| "Backend runtime is missing session token".to_string())?;
            return Ok(StartBackendResponse {
                ok: true,
                base_url,
                ws_base_url,
                session_token,
                api_pid: runtime.api_pid,
                runtime_worker_pid: runtime.runtime_worker_pid,
                error: None,
            });
        }
    }

    if let Some(external) = parse_external_backend_config()? {
        if !wait_for_health(&external.host, external.port, STARTUP_TIMEOUT) {
            return Err("External backend is not ready: /api/health check failed".to_string());
        }

        let mut runtime = state
            .runtime
            .lock()
            .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
        runtime.api_process = None;
        runtime.runtime_worker_process = None;
        runtime.base_url = Some(external.base_url.clone());
        runtime.ws_base_url = Some(external.ws_base_url.clone());
        runtime.session_token = Some(external.session_token.clone());
        runtime.api_pid = None;
        runtime.runtime_worker_pid = None;

        return Ok(StartBackendResponse {
            ok: true,
            base_url: external.base_url,
            ws_base_url: external.ws_base_url,
            session_token: external.session_token,
            api_pid: None,
            runtime_worker_pid: None,
            error: None,
        });
    }

    let port = pick_open_port()?;
    let session_token = generate_session_token();
    let base_url = format!("http://{}:{}/api", BACKEND_HOST, port);
    let ws_base_url = format!("ws://{}:{}", BACKEND_HOST, port);

    let start = match spawn_sidecar_backend(&app, port, &session_token, state.recent_errors.clone())
    {
        Ok(result) => result,
        Err(sidecar_err) => {
            if cfg!(debug_assertions) {
                spawn_dev_backend_pair(port, &session_token)
                    .map_err(|dev_err| format!("{}; fallback failed: {}", sidecar_err, dev_err))?
            } else {
                return Err(sidecar_err);
            }
        }
    };

    if !wait_for_health(BACKEND_HOST, port, STARTUP_TIMEOUT) {
        let mut api_process = start.api_process;
        let mut runtime_worker_process = start.runtime_worker_process;
        api_process.kill();
        runtime_worker_process.kill();
        // Collect recent error logs for better error message
        let error_details = if let Ok(errors) = state.recent_errors.lock() {
            if errors.is_empty() {
                String::new()
            } else {
                format!("\n\nRecent logs:\n{}", errors.join("\n"))
            }
        } else {
            String::new()
        };
        return Err(format!(
            "Backend startup timeout: /api/health did not become ready{}",
            error_details
        ));
    }

    let mut runtime = state
        .runtime
        .lock()
        .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
    runtime.api_process = Some(start.api_process);
    runtime.runtime_worker_process = Some(start.runtime_worker_process);
    runtime.base_url = Some(base_url.clone());
    runtime.ws_base_url = Some(ws_base_url.clone());
    runtime.session_token = Some(session_token.clone());
    runtime.api_pid = start.api_pid;
    runtime.runtime_worker_pid = start.runtime_worker_pid;

    Ok(StartBackendResponse {
        ok: true,
        base_url,
        ws_base_url,
        session_token,
        api_pid: runtime.api_pid,
        runtime_worker_pid: runtime.runtime_worker_pid,
        error: None,
    })
}

#[tauri::command]
fn stop_backend(state: State<'_, BackendState>) -> Result<StopBackendResponse, String> {
    stop_backend_inner(&state)?;
    Ok(StopBackendResponse { ok: true })
}

#[tauri::command]
fn backend_status(state: State<'_, BackendState>) -> Result<BackendStatusResponse, String> {
    let runtime = state
        .runtime
        .lock()
        .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
    Ok(BackendStatusResponse {
        running: runtime.base_url.is_some(),
        base_url: runtime.base_url.clone(),
        ws_base_url: runtime.ws_base_url.clone(),
        api_pid: runtime.api_pid,
        runtime_worker_pid: runtime.runtime_worker_pid,
    })
}

#[tauri::command]
fn get_backend_base_url(state: State<'_, BackendState>) -> Result<BackendBaseUrlResponse, String> {
    let runtime = state
        .runtime
        .lock()
        .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
    Ok(BackendBaseUrlResponse {
        base_url: runtime.base_url.clone(),
    })
}

#[tauri::command]
fn set_close_to_tray_enabled(
    state: State<'_, desktop_presence::DesktopPresenceState>,
    enabled: bool,
) -> Result<(), String> {
    state.set_close_to_tray_enabled(enabled)
}

#[tauri::command]
fn confirm_exit_app(app: AppHandle, backend_state: State<'_, BackendState>) -> Result<(), String> {
    stop_backend_inner(&backend_state)?;
    app.exit(0);
    Ok(())
}

#[tauri::command]
fn cancel_exit_request() -> Result<(), String> {
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState::default())
        .manage(desktop_presence::DesktopPresenceState::default())
        .setup(|app| desktop_presence::setup(app.handle()).map_err(Into::into))
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { api, .. } => {
                let state: State<'_, desktop_presence::DesktopPresenceState> = window.state();
                match state.close_action() {
                    Ok(desktop_presence::CloseAction::HideToTray) => {
                        api.prevent_close();
                        let _ = desktop_presence::hide_main_window(window.app_handle());
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
            start_backend,
            stop_backend,
            backend_status,
            get_backend_base_url,
            set_close_to_tray_enabled,
            confirm_exit_app,
            cancel_exit_request
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Magi desktop application");
}
