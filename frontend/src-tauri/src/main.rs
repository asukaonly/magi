// Hide the console window in release builds on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod desktop_presence;
mod frontmost_app_monitor;

use magi_gateway::{api, ipc, notification_bridge};

#[cfg(unix)]
use libc::{kill, SIGTERM};
use serde::Serialize;
use std::env;
use std::fs::{self, OpenOptions};
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
    python_process: Option<BackendProcess>,
    axum_shutdown: Option<tokio::sync::oneshot::Sender<()>>,
    bridge_shutdown: Option<tokio::sync::watch::Sender<bool>>,
    base_url: Option<String>,
    session_token: Option<String>,
    python_pid: Option<u32>,
    /// Stored between start_backend and poll_backend_startup.
    ipc_socket_path: Option<String>,
    main_port: Option<u16>,
    /// True once Axum gateway and IPC are wired up.
    gateway_ready: bool,
}

struct ExternalBackendConfig {
    host: String,
    port: u16,
    base_url: String,
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
    process: BackendProcess,
    pid: Option<u32>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct StartBackendResponse {
    ok: bool,
    base_url: String,
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

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PollStartupResponse {
    ready: bool,
    phase: String,
    error: Option<String>,
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

/// Remove stale worker ready file.
fn remove_ready_file() {
    if let Ok(home) = env::var("HOME")
        .or_else(|_| env::var("USERPROFILE"))
        .map(PathBuf::from)
    {
        let runtime_dir = home.join(".magi").join("runtime");
        let _ = fs::remove_file(runtime_dir.join("worker.ready"));
        let _ = fs::remove_file(runtime_dir.join("gateway.port"));
    }
}

fn write_gateway_port_file(port: u16) {
    if let Ok(home) = env::var("HOME")
        .or_else(|_| env::var("USERPROFILE"))
        .map(PathBuf::from)
    {
        let runtime_dir = home.join(".magi").join("runtime");
        let _ = fs::create_dir_all(&runtime_dir);
        let _ = fs::write(runtime_dir.join("gateway.port"), port.to_string());
    }
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
    let session_token = env::var("MAGI_DESKTOP_SESSION_TOKEN").unwrap_or_default();

    Ok(Some(ExternalBackendConfig {
        host,
        port,
        base_url,
        session_token,
    }))
}

fn spawn_sidecar_role(
    app: &AppHandle,
    role: &str,
    port: Option<u16>,
    session_token: &str,
    ipc_socket_path: &str,
    recent_errors: Arc<Mutex<Vec<String>>>,
) -> Result<(BackendProcess, Option<u32>), String> {
    let mut args = vec![
        "--role".to_string(),
        role.to_string(),
        "--no-reload".to_string(),
    ];
    if role == "api" || role == "unified" {
        let port_text = port
            .ok_or_else(|| format!("{} role requires a port", role))?
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
        .env("MAGI_IPC_SOCKET", ipc_socket_path)
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

fn dev_backend_log_path() -> Result<PathBuf, String> {
    if let Ok(configured) = env::var("MAGI_BACKEND_LOG_FILE") {
        let trimmed = configured.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed));
        }
    }

    let home_dir = env::var("HOME")
        .or_else(|_| env::var("USERPROFILE"))
        .map(PathBuf::from)
        .map_err(|_| {
            "Neither HOME nor USERPROFILE is set for desktop dev backend logging".to_string()
        })?;
    Ok(home_dir
        .join(".magi")
        .join("logs")
        .join("backend-dev-hot.log"))
}

fn open_dev_backend_log_stdio() -> Result<(Stdio, Stdio), String> {
    let log_path = dev_backend_log_path()?;
    if let Some(parent) = log_path.parent() {
        fs::create_dir_all(parent)
            .map_err(|err| format!("Failed to create backend log directory: {err}"))?;
    }

    let stdout_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|err| format!("Failed to open backend log file: {err}"))?;
    let stderr_file = stdout_file
        .try_clone()
        .map_err(|err| format!("Failed to clone backend log file handle: {err}"))?;

    Ok((Stdio::from(stdout_file), Stdio::from(stderr_file)))
}

fn spawn_dev_backend_role(
    role: &str,
    port: Option<u16>,
    session_token: &str,
    ipc_socket_path: &str,
) -> Result<(BackendProcess, Option<u32>), String> {
    let backend_dir = find_backend_dir()?;
    let (stdout, stderr) = open_dev_backend_log_stdio()?;

    let mut command = Command::new("python");
    command
        .arg("run_server.py")
        .arg("--role")
        .arg(role)
        .arg("--no-reload")
        .env("MAGI_DESKTOP_MODE", "1")
        .env("MAGI_DESKTOP_SESSION_TOKEN", session_token)
        .env("MAGI_IPC_SOCKET", ipc_socket_path)
        .current_dir(backend_dir)
        .stdout(stdout)
        .stderr(stderr);

    if role == "api" || role == "unified" {
        let port_text = port
            .ok_or_else(|| format!("{} role requires a port", role))?
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
    session_token: &str,
    ipc_socket_path: &str,
    recent_errors: Arc<Mutex<Vec<String>>>,
) -> Result<ManagedBackendStart, String> {
    let (process, pid) = spawn_sidecar_role(
        app,
        "ipc_worker",
        None,
        session_token,
        ipc_socket_path,
        recent_errors,
    )?;
    Ok(ManagedBackendStart { process, pid })
}

fn spawn_dev_backend_pair(
    session_token: &str,
    ipc_socket_path: &str,
) -> Result<ManagedBackendStart, String> {
    let (process, pid) =
        spawn_dev_backend_role("ipc_worker", None, session_token, ipc_socket_path)?;
    Ok(ManagedBackendStart { process, pid })
}

fn stop_backend_inner(state: &BackendState) -> Result<(), String> {
    let mut runtime = state
        .runtime
        .lock()
        .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
    let python_pid = runtime.python_pid;
    if let Some(mut process) = runtime.python_process.take() {
        // Graceful shutdown: SIGTERM → wait → force kill
        if let Some(pid) = python_pid {
            let _ = send_termination_signal(pid);
            if !wait_for_process_stop(&mut process, python_pid, SHUTDOWN_TIMEOUT) {
                process.kill();
            }
        } else {
            process.kill();
        }
    }
    if let Some(tx) = runtime.axum_shutdown.take() {
        let _ = tx.send(());
    }
    if let Some(tx) = runtime.bridge_shutdown.take() {
        let _ = tx.send(true);
    }
    remove_ready_file();
    runtime.base_url = None;
    runtime.session_token = None;
    runtime.python_pid = None;
    runtime.ipc_socket_path = None;
    runtime.main_port = None;
    runtime.gateway_ready = false;
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
            let session_token = runtime
                .session_token
                .clone()
                .ok_or_else(|| "Backend runtime is missing session token".to_string())?;
            return Ok(StartBackendResponse {
                ok: true,
                base_url,
                session_token,
                api_pid: runtime.python_pid,
                runtime_worker_pid: runtime.python_pid,
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
        runtime.python_process = None;
        runtime.base_url = Some(external.base_url.clone());
        runtime.session_token = Some(external.session_token.clone());
        runtime.python_pid = None;
        runtime.gateway_ready = true;

        return Ok(StartBackendResponse {
            ok: true,
            base_url: external.base_url,
            session_token: external.session_token,
            api_pid: None,
            runtime_worker_pid: None,
            error: None,
        });
    }

    let main_port = pick_open_port()?;
    let session_token = generate_session_token();
    let base_url = format!("http://{}:{}/api", BACKEND_HOST, main_port);

    // Compute IPC socket address.
    // Unix: domain socket under ~/.magi/runtime/ipc.sock
    // Windows: TCP loopback 127.0.0.1:<port>
    let ipc_socket_path = if cfg!(windows) {
        let ipc_port = pick_open_port().map_err(|e| format!("Failed to pick IPC port: {e}"))?;
        format!("127.0.0.1:{}", ipc_port)
    } else {
        let home = env::var("HOME")
            .map(PathBuf::from)
            .map_err(|_| "HOME is not set".to_string())?;
        let runtime_dir = home.join(".magi").join("runtime");
        fs::create_dir_all(&runtime_dir)
            .map_err(|e| format!("Failed to create runtime dir: {e}"))?;
        // Clean up stale ipc-*.sock files left by previous crashed sessions
        if let Ok(entries) = fs::read_dir(&runtime_dir) {
            for entry in entries.flatten() {
                let name = entry.file_name();
                let name = name.to_string_lossy();
                if name.starts_with("ipc") && name.ends_with(".sock") {
                    let _ = fs::remove_file(entry.path());
                }
            }
        }
        runtime_dir.join("ipc.sock").to_string_lossy().to_string()
    };

    // Remove stale ready / port files before spawning
    remove_ready_file();

    let start = if cfg!(debug_assertions) {
        spawn_dev_backend_pair(&session_token, &ipc_socket_path)?
    } else {
        spawn_sidecar_backend(
            &app,
            &session_token,
            &ipc_socket_path,
            state.recent_errors.clone(),
        )?
    };

    // Store process and metadata — actual readiness is handled by poll_backend_startup.
    let mut runtime = state
        .runtime
        .lock()
        .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
    runtime.python_process = Some(start.process);
    runtime.base_url = Some(base_url.clone());
    runtime.session_token = Some(session_token.clone());
    runtime.python_pid = start.pid;
    runtime.ipc_socket_path = Some(ipc_socket_path);
    runtime.main_port = Some(main_port);
    runtime.gateway_ready = false;

    Ok(StartBackendResponse {
        ok: true,
        base_url,
        session_token,
        api_pid: start.pid,
        runtime_worker_pid: start.pid,
        error: None,
    })
}

/// Non-blocking startup poll.  Returns the current phase so the frontend can
/// display progress.  When the Python worker is ready, this command finishes
/// the remaining setup (IPC connect, Axum gateway, notification bridge) in a
/// single call, then returns `ready: true` from that point on.
#[tauri::command]
fn poll_backend_startup(
    app: AppHandle,
    state: State<'_, BackendState>,
) -> Result<PollStartupResponse, String> {
    // Fast path: already fully started.
    {
        let runtime = state
            .runtime
            .lock()
            .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
        if runtime.gateway_ready {
            return Ok(PollStartupResponse {
                ready: true,
                phase: "ready".to_string(),
                error: None,
            });
        }
        if runtime.base_url.is_none() {
            return Err("start_backend has not been called yet".to_string());
        }
    }

    // Check whether the Python worker has written its ready file.
    let ready_file_exists = {
        let home = env::var("HOME")
            .or_else(|_| env::var("USERPROFILE"))
            .map(PathBuf::from)
            .unwrap_or_default();
        home.join(".magi")
            .join("runtime")
            .join("worker.ready")
            .exists()
    };

    if !ready_file_exists {
        return Ok(PollStartupResponse {
            ready: false,
            phase: "waiting_for_worker".to_string(),
            error: None,
        });
    }

    // Worker is ready — finish setup under the lock.
    let mut runtime = state
        .runtime
        .lock()
        .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;

    // Double-check (another poll call could have completed setup concurrently).
    if runtime.gateway_ready {
        return Ok(PollStartupResponse {
            ready: true,
            phase: "ready".to_string(),
            error: None,
        });
    }

    let ipc_socket_path = runtime
        .ipc_socket_path
        .clone()
        .ok_or_else(|| "Missing IPC socket path".to_string())?;
    let main_port = runtime
        .main_port
        .ok_or_else(|| "Missing main port".to_string())?;

    // Connect IPC client to Python worker (required)
    let ipc_client = match tauri::async_runtime::block_on(ipc::IpcClient::connect(&ipc_socket_path))
    {
        Ok((client, _event_rx)) => std::sync::Arc::new(client),
        Err(e) => {
            // Kill the process on IPC failure.
            if let Some(mut process) = runtime.python_process.take() {
                process.kill();
            }
            runtime.base_url = None;
            runtime.session_token = None;
            runtime.python_pid = None;
            return Ok(PollStartupResponse {
                ready: false,
                phase: "error".to_string(),
                error: Some(format!("IPC connect failed: {e}")),
            });
        }
    };

    let api_state = api::state::ApiState { ipc_client };
    let router = api::build_router(api_state);

    // Ensure performance-critical indexes exist on SQLite databases
    magi_gateway::db::ensure_indexes();

    let std_listener = match std::net::TcpListener::bind((BACKEND_HOST, main_port)) {
        Ok(l) => l,
        Err(e) => {
            return Ok(PollStartupResponse {
                ready: false,
                phase: "error".to_string(),
                error: Some(format!(
                    "Failed to bind Axum listener on port {}: {}",
                    main_port, e
                )),
            });
        }
    };
    if let Err(e) = std_listener.set_nonblocking(true) {
        return Ok(PollStartupResponse {
            ready: false,
            phase: "error".to_string(),
            error: Some(format!("Failed to set listener non-blocking: {e}")),
        });
    }

    write_gateway_port_file(main_port);

    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel::<()>();

    tauri::async_runtime::spawn(async move {
        let listener = tokio::net::TcpListener::from_std(std_listener)
            .expect("Failed to convert to tokio TcpListener");
        magi_gateway::axum::serve(listener, router)
            .with_graceful_shutdown(async {
                let _ = shutdown_rx.await;
            })
            .await
            .ok();
    });

    // Start notification bridge (polls runtime_trace.db → Tauri events)
    let (bridge_shutdown_tx, bridge_shutdown_rx) = tokio::sync::watch::channel(false);
    let bridge_app = app.clone();
    let event_emitter: notification_bridge::EventEmitFn =
        std::sync::Arc::new(move |event, payload| {
            let _ = bridge_app.emit(event, payload);
        });
    tauri::async_runtime::spawn(async move {
        notification_bridge::run_notification_bridge(Some(event_emitter), bridge_shutdown_rx).await;
    });

    runtime.axum_shutdown = Some(shutdown_tx);
    runtime.bridge_shutdown = Some(bridge_shutdown_tx);
    runtime.gateway_ready = true;

    Ok(PollStartupResponse {
        ready: true,
        phase: "ready".to_string(),
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
        api_pid: runtime.python_pid,
        runtime_worker_pid: runtime.python_pid,
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
fn set_start_minimized(
    state: State<'_, desktop_presence::DesktopPresenceState>,
    enabled: bool,
) -> Result<(), String> {
    state.set_start_minimized(enabled)
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
    let log_dir = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| std::path::PathBuf::from("."))
        .join(".magi")
        .join("logs");

    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::new()
                .target(tauri_plugin_log::Target::new(
                    tauri_plugin_log::TargetKind::Folder {
                        path: log_dir,
                        file_name: Some("desktop".to_string()),
                    },
                ))
                .target(tauri_plugin_log::Target::new(
                    tauri_plugin_log::TargetKind::Stdout,
                ))
                .level(log::LevelFilter::Info)
                .max_file_size(10 * 1024 * 1024) // 10 MB per file
                .rotation_strategy(tauri_plugin_log::RotationStrategy::KeepSome(5))
                .build(),
        )
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
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState::default())
        .manage(desktop_presence::DesktopPresenceState::default())
        .setup(|app| {
            if let Err(err) = desktop_presence::setup(app.handle()) {
                eprintln!(
                    "Optional desktop presence setup is unavailable; continuing without tray integration: {err}"
                );
            }
            if let Err(err) = frontmost_app_monitor::setup_monitor() {
                eprintln!(
                    "Optional frontmost app monitor is unavailable; continuing without activation tracking: {err}"
                );
            }
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
            poll_backend_startup,
            stop_backend,
            backend_status,
            get_backend_base_url,
            set_close_to_tray_enabled,
            set_start_minimized,
            apply_start_minimized,
            confirm_exit_app,
            cancel_exit_request
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Magi desktop application");
}
