// Hide the console window in release builds on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod desktop_log_history;
mod desktop_presence;
mod dmg_cleanup;
mod external_url;
mod full_data_clear;
mod private_data;

use magi_gateway::{api, ipc, notification_bridge};

#[cfg(unix)]
use libc::{kill, SIGKILL, SIGTERM};
use serde::Serialize;
use std::env;
use std::ffi::OsString;
use std::fs::{self, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager, State};

const BACKEND_HOST: &str = "127.0.0.1";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(25);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(3);
const SHUTDOWN_POLL_INTERVAL: Duration = Duration::from_millis(100);
const BACKEND_LOG_TAIL_BYTES: u64 = 64 * 1024;
const DESKTOP_LOG_MAX_BYTES: u64 = 50 * 1024 * 1024;
const DESKTOP_SESSION_TOKEN_ENV: &str = "MAGI_DESKTOP_SESSION_TOKEN";
const INTERNAL_IPC_TOKEN_ENV: &str = "MAGI_IPC_AUTH_TOKEN";
const BACKEND_LOG_FILE_ENV: &str = "MAGI_BACKEND_LOG_FILE";
const FULL_DATA_CLEAR_TRANSACTION_ENV: &str = "MAGI_FULL_DATA_CLEAR_TRANSACTION_ID";

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

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
    ipc_auth_token: Option<String>,
    python_pid: Option<u32>,
    /// Stored between start_backend and poll_backend_startup.
    ipc_socket_path: Option<String>,
    main_port: Option<u16>,
    /// True once Axum gateway and IPC are wired up.
    gateway_ready: bool,
}

struct ExternalBackendConfig {
    connect_host: String,
    host_header: String,
    port: u16,
    base_url: String,
    session_token: String,
}

enum BackendProcess {
    Dev(Option<Child>),
}

impl BackendProcess {
    fn kill(&mut self) {
        let Self::Dev(child) = self;
        if let Some(process) = child.as_mut() {
            let _ = process.kill();
            // On Windows, TerminateProcess returns before the OS releases the
            // executable's file handles. Reap synchronously so a follow-up
            // installer can overwrite sidecar-dist binaries.
            let _ = process.wait();
        }
        child.take();
    }

    fn wait_for_exit(&mut self, timeout: Duration) -> bool {
        let Self::Dev(child) = self;
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
struct BackendStartupDiagnosticsResponse {
    log_path: Option<String>,
    log_excerpt: Option<String>,
    log_read_error: Option<String>,
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

fn wait_for_health(config: &ExternalBackendConfig, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if let Ok(mut stream) = TcpStream::connect((config.connect_host.as_str(), config.port)) {
            let request = format!(
                "GET /api/health HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",
                config.host_header
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

#[cfg(windows)]
fn suppress_child_console_window(command: &mut Command) {
    use std::os::windows::process::CommandExt;

    command.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn suppress_child_console_window(_command: &mut Command) {}

fn isolate_python_worker_environment(command: &mut Command) {
    command.env_remove(DESKTOP_SESSION_TOKEN_ENV);
    command.env_remove(INTERNAL_IPC_TOKEN_ENV);
    command.env_remove(FULL_DATA_CLEAR_TRANSACTION_ENV);
}

fn configure_ipc_auth_environment(command: &mut Command, auth_token: &str) {
    command.env(INTERNAL_IPC_TOKEN_ENV, auth_token);
}

fn configure_full_data_clear_environment(command: &mut Command, transaction_id: Option<&str>) {
    if let Some(transaction_id) = transaction_id {
        command.env(FULL_DATA_CLEAR_TRANSACTION_ENV, transaction_id);
    }
}

fn should_reuse_running_backend(running: bool, full_data_clear_pending: bool) -> bool {
    running && !full_data_clear_pending
}

#[cfg(unix)]
fn send_termination_signal(pid: u32) -> bool {
    unsafe { kill(pid as i32, SIGTERM) == 0 }
}

#[cfg(windows)]
fn send_termination_signal(pid: u32) -> bool {
    // `taskkill` without `/F` sends WM_CLOSE first, giving the sidecar a chance
    // to flush before we force-kill. `/T` includes the whole process tree —
    // the python sidecar spawns plugin python subprocesses that also hold
    // file locks under sidecar-dist\_internal.
    let mut command = Command::new("taskkill");
    suppress_child_console_window(&mut command);
    command
        .args(["/T", "/PID", &pid.to_string()])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

#[cfg(not(any(unix, windows)))]
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

#[cfg(windows)]
fn is_pid_running(pid: u32) -> bool {
    // `tasklist /FI "PID eq <pid>"` prints a header line plus "INFO: No tasks..."
    // when the pid is gone, and a real row when it's alive.
    let mut command = Command::new("tasklist");
    suppress_child_console_window(&mut command);
    let output = match command
        .args(["/FI", &format!("PID eq {pid}"), "/NH", "/FO", "CSV"])
        .stderr(Stdio::null())
        .output()
    {
        Ok(output) => output,
        Err(_) => return false,
    };
    let stdout = String::from_utf8_lossy(&output.stdout);
    stdout.contains(&format!(",\"{pid}\","))
}

#[cfg(not(any(unix, windows)))]
fn is_pid_running(_pid: u32) -> bool {
    false
}

#[cfg(target_os = "macos")]
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
    if process.wait_for_exit(timeout) {
        return true;
    }

    #[cfg(any(unix, windows))]
    if let Some(pid) = pid {
        return !is_pid_running(pid);
    }
    let _ = pid;
    false
}

#[cfg(unix)]
fn send_kill_signal(pid: u32) -> bool {
    unsafe { kill(pid as i32, SIGKILL) == 0 }
}

#[cfg(windows)]
fn send_kill_signal(pid: u32) -> bool {
    // `/F /T` force-kills the whole tree — needed so any plugin python
    // grandchildren the sidecar spawned also die.
    let mut command = Command::new("taskkill");
    suppress_child_console_window(&mut command);
    command
        .args(["/F", "/T", "/PID", &pid.to_string()])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

#[cfg(target_os = "macos")]
fn parse_sidecar_pids_from_ps(output: &str, sidecar_path: &Path, current_pid: u32) -> Vec<u32> {
    let target = sidecar_path.to_string_lossy();
    output
        .lines()
        .filter_map(|line| {
            let trimmed = line.trim();
            let separator_index = trimmed.find(char::is_whitespace)?;
            let pid = trimmed[..separator_index].parse::<u32>().ok()?;
            if pid == current_pid {
                return None;
            }
            let command_path = trimmed[separator_index..].trim();
            (command_path == target).then_some(pid)
        })
        .collect()
}

#[cfg(target_os = "macos")]
fn find_stale_sidecar_pids(sidecar_path: &Path) -> Result<Vec<u32>, String> {
    let output = Command::new("ps")
        .args(["-axo", "pid=,comm="])
        .output()
        .map_err(|err| format!("Failed to inspect running processes: {err}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if stderr.is_empty() {
            "Failed to inspect running processes".to_string()
        } else {
            format!("Failed to inspect running processes: {stderr}")
        });
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    Ok(parse_sidecar_pids_from_ps(
        &stdout,
        sidecar_path,
        std::process::id(),
    ))
}

#[cfg(target_os = "macos")]
fn terminate_stale_sidecar_processes(pids: &[u32]) -> Result<(), String> {
    for pid in pids {
        let _ = send_termination_signal(*pid);
    }

    for pid in pids {
        if wait_for_pid_exit(*pid, SHUTDOWN_TIMEOUT) {
            continue;
        }
        let _ = send_kill_signal(*pid);
        if !wait_for_pid_exit(*pid, SHUTDOWN_TIMEOUT) {
            return Err(format!(
                "Failed to stop stale backend sidecar process {pid}"
            ));
        }
    }

    Ok(())
}

#[cfg(target_os = "macos")]
fn cleanup_stale_sidecar_processes(app: &AppHandle) -> Result<(), String> {
    let sidecar_path = resolve_sidecar_path(app)?;
    let pids = find_stale_sidecar_pids(&sidecar_path)?;
    if pids.is_empty() {
        return Ok(());
    }

    log::warn!(
        "Stopping stale backend sidecar processes before startup: {:?}",
        pids
    );
    terminate_stale_sidecar_processes(&pids)
}

#[cfg(not(target_os = "macos"))]
fn cleanup_stale_sidecar_processes(_app: &AppHandle) -> Result<(), String> {
    Ok(())
}

fn parse_external_backend_config() -> Result<Option<ExternalBackendConfig>, String> {
    let gateway_url = match env::var("MAGI_TAURI_EXTERNAL_GATEWAY_URL") {
        Ok(value) => value,
        Err(env::VarError::NotPresent) => return Ok(None),
        Err(env::VarError::NotUnicode(_)) => {
            return Err("MAGI_TAURI_EXTERNAL_GATEWAY_URL must be valid text".to_string())
        }
    };
    let session_token = env::var(DESKTOP_SESSION_TOKEN_ENV).ok();
    build_external_backend_config(&gateway_url, session_token).map(Some)
}

fn build_external_backend_config(
    gateway_url: &str,
    session_token: Option<String>,
) -> Result<ExternalBackendConfig, String> {
    let session_token = session_token
        .ok_or_else(|| "External gateway requires MAGI_DESKTOP_SESSION_TOKEN".to_string())?;
    let session_token = session_token.trim();
    if session_token.is_empty() {
        return Err("External gateway session token must not be empty".to_string());
    }

    let raw = gateway_url.trim();
    let authority_and_path = raw
        .strip_prefix("http://")
        .ok_or_else(|| "External gateway URL must use http".to_string())?;
    if authority_and_path.is_empty()
        || authority_and_path.contains('?')
        || authority_and_path.contains('#')
        || authority_and_path.contains('@')
    {
        return Err("External gateway URL is invalid".to_string());
    }

    let (authority, path) = authority_and_path
        .split_once('/')
        .map(|(authority, path)| (authority, format!("/{path}")))
        .unwrap_or((authority_and_path, String::new()));
    let normalized_path = path.trim_end_matches('/');
    if !normalized_path.is_empty() && normalized_path != "/api" {
        return Err("External gateway URL path must be empty or /api".to_string());
    }

    let (connect_host, display_host, port) = parse_loopback_authority(authority)?;
    let host_header = if port == 80 {
        display_host.clone()
    } else {
        format!("{display_host}:{port}")
    };
    let origin = if port == 80 {
        format!("http://{display_host}")
    } else {
        format!("http://{display_host}:{port}")
    };

    Ok(ExternalBackendConfig {
        connect_host,
        host_header,
        port,
        base_url: format!("{origin}/api"),
        session_token: session_token.to_string(),
    })
}

fn parse_loopback_authority(authority: &str) -> Result<(String, String, u16), String> {
    if authority.is_empty() {
        return Err("External gateway URL is missing a host".to_string());
    }

    if authority.starts_with('[') || authority.matches(':').count() > 1 {
        return Err("External gateway URL must use localhost or IPv4 loopback".to_string());
    }
    let (host, port_text) = authority
        .rsplit_once(':')
        .map(|(host, port)| (host, Some(port)))
        .unwrap_or((authority, None));
    let host = host.to_string();
    let display_host = host.clone();

    let loopback = host.eq_ignore_ascii_case("localhost")
        || host
            .parse::<std::net::IpAddr>()
            .map(|address| address.is_loopback())
            .unwrap_or(false);
    if !loopback {
        return Err("External gateway URL must use a loopback host".to_string());
    }
    let port = match port_text {
        Some("") => return Err("External gateway URL port is invalid".to_string()),
        Some(value) => value
            .parse::<u16>()
            .ok()
            .filter(|port| *port > 0)
            .ok_or_else(|| "External gateway URL port is invalid".to_string())?,
        None => 80,
    };
    Ok((host, display_host, port))
}

fn first_existing_dir(candidates: impl IntoIterator<Item = PathBuf>) -> Option<PathBuf> {
    candidates.into_iter().find(|dir| dir.is_dir())
}

fn ordered_builtin_avatar_dirs(
    resource_dir: Option<PathBuf>,
    source_tree_avatar_dir: PathBuf,
) -> Vec<PathBuf> {
    let mut packaged_dirs = Vec::new();
    if let Some(resource_dir) = resource_dir {
        packaged_dirs.push(
            resource_dir
                .join("sidecar-dist")
                .join("_internal")
                .join("personalities")
                .join("avatar"),
        );
        packaged_dirs.push(
            resource_dir
                .join("sidecar-dist")
                .join("personalities")
                .join("avatar"),
        );
    }

    if cfg!(debug_assertions) {
        let mut candidates = vec![source_tree_avatar_dir];
        candidates.extend(packaged_dirs);
        candidates
    } else {
        packaged_dirs.push(source_tree_avatar_dir);
        packaged_dirs
    }
}

/// Resolve the builtin avatar directory.
fn resolve_builtin_avatar_dir(app: &AppHandle) -> Option<PathBuf> {
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    // CARGO_MANIFEST_DIR = frontend/src-tauri → project root = ../..
    let project_root = manifest_dir.parent()?.parent()?;
    let source_tree_avatar_dir = project_root
        .join("backend")
        .join("personalities")
        .join("avatar");

    first_existing_dir(ordered_builtin_avatar_dirs(
        app.path().resource_dir().ok(),
        source_tree_avatar_dir,
    ))
}

/// Resolve the user avatar directory (~/.magi/personalities/avatar).
fn resolve_user_avatar_dir() -> Option<PathBuf> {
    let home = env::var("HOME")
        .or_else(|_| env::var("USERPROFILE"))
        .ok()
        .map(PathBuf::from)?;
    let dir = home.join(".magi").join("personalities").join("avatar");
    let _ = fs::create_dir_all(&dir);
    Some(dir)
}

fn resolve_sidecar_path(app: &AppHandle) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Failed to resolve resource directory: {e}"))?;

    #[cfg(windows)]
    let binary_name = "magi-backend.exe";
    #[cfg(not(windows))]
    let binary_name = "magi-backend";

    let sidecar_path = resource_dir.join("sidecar-dist").join(binary_name);
    if !sidecar_path.exists() {
        return Err(format!(
            "Sidecar binary not found at: {}",
            sidecar_path.display()
        ));
    }
    Ok(sidecar_path)
}

fn plugin_python_candidates_from_resource_dir(resource_dir: &Path) -> Vec<PathBuf> {
    #[cfg(windows)]
    let candidates = vec![
        resource_dir.join("plugin-python").join("python.exe"),
        resource_dir
            .join("plugin-python")
            .join("Scripts")
            .join("python.exe"),
    ];

    #[cfg(not(windows))]
    let candidates = vec![
        resource_dir
            .join("plugin-python")
            .join("bin")
            .join("python"),
        resource_dir
            .join("plugin-python")
            .join("bin")
            .join("python3"),
    ];

    candidates
}

#[cfg(test)]
fn plugin_python_path_from_resource_dir(resource_dir: &Path) -> PathBuf {
    plugin_python_candidates_from_resource_dir(resource_dir)
        .into_iter()
        .next()
        .unwrap_or_else(|| resource_dir.join("plugin-python"))
}

fn resolve_plugin_python_path(app: &AppHandle) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Failed to resolve resource directory: {e}"))?;
    let candidates = plugin_python_candidates_from_resource_dir(&resource_dir);
    for candidate in &candidates {
        if candidate.exists() {
            return Ok(candidate.clone());
        }
    }
    let checked = candidates
        .iter()
        .map(|path| path.display().to_string())
        .collect::<Vec<_>>()
        .join(", ");
    Err(format!(
        "Plugin Python runtime not found. Checked: {checked}"
    ))
}

fn home_dir() -> Result<PathBuf, String> {
    env::var("HOME")
        .or_else(|_| env::var("USERPROFILE"))
        .map(PathBuf::from)
        .map_err(|_| "Neither HOME nor USERPROFILE is set".to_string())
}

fn desktop_log_dir() -> Result<PathBuf, String> {
    match home_dir() {
        Ok(home) => Ok(home.join(".magi").join("logs")),
        Err(_) => env::current_dir()
            .map(|current| current.join(".magi").join("logs"))
            .map_err(|err| format!("Failed to resolve desktop log directory: {err}")),
    }
}

fn full_data_clear_marker_path() -> Result<PathBuf, String> {
    Ok(home_dir()?
        .join(".magi")
        .join("runtime")
        .join("full-data-clear.pending.json"))
}

fn sidecar_backend_log_path() -> Result<PathBuf, String> {
    Ok(desktop_log_dir()?.join("backend.log"))
}

fn configure_backend_log_environment(command: &mut Command, backend_log_path: &Path) {
    command.env(BACKEND_LOG_FILE_ENV, backend_log_path);
}

fn open_sidecar_log_stdio() -> Result<(Stdio, Stdio), String> {
    let log_path = sidecar_backend_log_path()?;
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

fn spawn_sidecar_role(
    app: &AppHandle,
    role: &str,
    port: Option<u16>,
    ipc_socket_path: &str,
    ipc_auth_token: &str,
    full_data_clear_transaction_id: Option<&str>,
) -> Result<(BackendProcess, Option<u32>), String> {
    let sidecar_path = resolve_sidecar_path(app)?;
    let plugin_python_path = resolve_plugin_python_path(app)?;

    // Ensure executable permission on Unix
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&sidecar_path)
            .map_err(|e| format!("Failed to read sidecar metadata: {e}"))?
            .permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&sidecar_path, perms)
            .map_err(|e| format!("Failed to set sidecar executable permission: {e}"))?;

        let mut plugin_python_perms = fs::metadata(&plugin_python_path)
            .map_err(|e| format!("Failed to read plugin Python metadata: {e}"))?
            .permissions();
        plugin_python_perms.set_mode(0o755);
        fs::set_permissions(&plugin_python_path, plugin_python_perms)
            .map_err(|e| format!("Failed to set plugin Python executable permission: {e}"))?;
    }

    let backend_log_path = sidecar_backend_log_path()?;
    let (stdout, stderr) = open_sidecar_log_stdio()?;

    let mut command = Command::new(&sidecar_path);
    suppress_child_console_window(&mut command);
    isolate_python_worker_environment(&mut command);
    configure_ipc_auth_environment(&mut command, ipc_auth_token);
    configure_full_data_clear_environment(&mut command, full_data_clear_transaction_id);
    configure_backend_log_environment(&mut command, &backend_log_path);
    command
        .arg("--role")
        .arg(role)
        .arg("--no-reload")
        .env("MAGI_DESKTOP_MODE", "1")
        .env("MAGI_IPC_SOCKET", ipc_socket_path)
        .env("MAGI_PLUGIN_PYTHON", plugin_python_path)
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
        .map_err(|err| format!("Failed to spawn backend sidecar: {err}"))?;
    let pid = Some(child.id());
    Ok((BackendProcess::Dev(Some(child)), pid))
}

fn find_project_root() -> Result<PathBuf, String> {
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let frontend_dir = manifest_dir
        .parent()
        .ok_or_else(|| "Cannot resolve frontend directory".to_string())?;
    Ok(frontend_dir
        .parent()
        .map(Path::to_path_buf)
        .ok_or_else(|| "Cannot resolve project root directory".to_string())?)
}

fn find_backend_dir() -> Result<PathBuf, String> {
    let project_root = find_project_root()?;
    let backend_dir = project_root.join("backend");
    if backend_dir.exists() {
        Ok(backend_dir)
    } else {
        Err("Backend directory not found for desktop dev fallback".to_string())
    }
}

fn resolve_dev_python_command(project_root: &Path) -> PathBuf {
    if let Ok(configured) = env::var("MAGI_BACKEND_PYTHON") {
        let trimmed = configured.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }

    let venv_python = if cfg!(windows) {
        project_root
            .join(".venv")
            .join("Scripts")
            .join("python.exe")
    } else {
        project_root.join(".venv").join("bin").join("python")
    };
    if venv_python.exists() {
        return venv_python;
    }

    PathBuf::from("python")
}

fn build_dev_pythonpath(project_root: &Path) -> Result<OsString, String> {
    let mut python_paths = vec![
        project_root.join("backend").join("src"),
        project_root.join("sdk").join("src"),
    ];

    if let Some(existing) = env::var_os("PYTHONPATH") {
        python_paths.extend(env::split_paths(&existing));
    }

    env::join_paths(python_paths)
        .map_err(|err| format!("Failed to build desktop dev PYTHONPATH: {err}"))
}

fn dev_backend_log_path() -> Result<PathBuf, String> {
    if let Ok(configured) = env::var(BACKEND_LOG_FILE_ENV) {
        let trimmed = configured.trim();
        if !trimmed.is_empty() {
            let configured_path = PathBuf::from(trimmed);
            let current_dir = env::current_dir()
                .map_err(|err| format!("Failed to resolve current directory: {err}"))?;
            return Ok(resolve_configured_log_path(&configured_path, &current_dir));
        }
    }

    Ok(desktop_log_dir()?.join("backend-dev-hot.log"))
}

fn resolve_configured_log_path(configured_path: &Path, current_dir: &Path) -> PathBuf {
    if configured_path.is_absolute() {
        configured_path.to_path_buf()
    } else {
        current_dir.join(configured_path)
    }
}

fn current_backend_log_path() -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        dev_backend_log_path()
    } else {
        sidecar_backend_log_path()
    }
}

fn read_text_file_tail(path: &Path, max_bytes: u64) -> Result<String, String> {
    let mut file = fs::File::open(path)
        .map_err(|err| format!("Failed to open backend log file {}: {err}", path.display()))?;
    let len = file
        .metadata()
        .map_err(|err| format!("Failed to read backend log metadata: {err}"))?
        .len();
    let offset = len.saturating_sub(max_bytes);
    file.seek(SeekFrom::Start(offset))
        .map_err(|err| format!("Failed to seek backend log file: {err}"))?;

    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)
        .map_err(|err| format!("Failed to read backend log file: {err}"))?;
    let mut text = String::from_utf8_lossy(&bytes).to_string();
    if offset > 0 {
        if let Some(newline) = text.find('\n') {
            text = text[(newline + 1)..].to_string();
        }
    }
    Ok(text)
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
    ipc_socket_path: &str,
    ipc_auth_token: &str,
    full_data_clear_transaction_id: Option<&str>,
) -> Result<(BackendProcess, Option<u32>), String> {
    let project_root = find_project_root()?;
    let backend_dir = find_backend_dir()?;
    let backend_log_path = dev_backend_log_path()?;
    let (stdout, stderr) = open_dev_backend_log_stdio()?;
    let python_command = resolve_dev_python_command(&project_root);
    let plugin_python = env::var_os("MAGI_PLUGIN_PYTHON")
        .unwrap_or_else(|| python_command.clone().into_os_string());
    let python_path = build_dev_pythonpath(&project_root)?;

    let mut command = Command::new(&python_command);
    suppress_child_console_window(&mut command);
    isolate_python_worker_environment(&mut command);
    configure_ipc_auth_environment(&mut command, ipc_auth_token);
    configure_full_data_clear_environment(&mut command, full_data_clear_transaction_id);
    configure_backend_log_environment(&mut command, &backend_log_path);
    command
        .arg("run_server.py")
        .arg("--role")
        .arg(role)
        .arg("--no-reload")
        .env("MAGI_DESKTOP_MODE", "1")
        .env("MAGI_IPC_SOCKET", ipc_socket_path)
        .env("MAGI_PLUGIN_PYTHON", plugin_python)
        .env("PYTHONPATH", python_path)
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

    let child = command.spawn().map_err(|err| {
        format!(
            "Failed to spawn backend with desktop dev Python {}: {err}",
            python_command.display()
        )
    })?;
    let pid = Some(child.id());
    Ok((BackendProcess::Dev(Some(child)), pid))
}

fn spawn_sidecar_backend(
    app: &AppHandle,
    ipc_socket_path: &str,
    ipc_auth_token: &str,
    full_data_clear_transaction_id: Option<&str>,
) -> Result<ManagedBackendStart, String> {
    let (process, pid) = spawn_sidecar_role(
        app,
        "ipc_worker",
        None,
        ipc_socket_path,
        ipc_auth_token,
        full_data_clear_transaction_id,
    )?;
    Ok(ManagedBackendStart { process, pid })
}

fn spawn_dev_backend_pair(
    ipc_socket_path: &str,
    ipc_auth_token: &str,
    full_data_clear_transaction_id: Option<&str>,
) -> Result<ManagedBackendStart, String> {
    let (process, pid) = spawn_dev_backend_role(
        "ipc_worker",
        None,
        ipc_socket_path,
        ipc_auth_token,
        full_data_clear_transaction_id,
    )?;
    Ok(ManagedBackendStart { process, pid })
}

fn stop_backend_inner(state: &BackendState) -> Result<(), String> {
    let mut runtime = state
        .runtime
        .lock()
        .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
    let python_pid = runtime.python_pid;
    if let Some(mut process) = runtime.python_process.take() {
        // Graceful shutdown: SIGTERM (or taskkill /T) → wait → force kill tree.
        // On Windows we additionally force a tree-kill so plugin python
        // grandchildren die before any installer tries to overwrite the
        // sidecar-dist files they hold open.
        if let Some(pid) = python_pid {
            let _ = send_termination_signal(pid);
            if !wait_for_process_stop(&mut process, python_pid, SHUTDOWN_TIMEOUT) {
                let _ = send_kill_signal(pid);
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
    runtime.ipc_auth_token = None;
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
    full_data_clear_state: State<'_, full_data_clear::FullDataClearRuntime>,
) -> Result<StartBackendResponse, String> {
    // Clear previous error logs
    if let Ok(mut errors) = state.recent_errors.lock() {
        errors.clear();
    }

    let pending_full_data_clear = full_data_clear_state.read()?;
    let running_backend = {
        let runtime = state
            .runtime
            .lock()
            .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
        let running = runtime.base_url.is_some();
        if should_reuse_running_backend(running, pending_full_data_clear.is_some()) {
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
        running
    };
    if running_backend {
        stop_backend_inner(&state)?;
    }

    if let Some(external) = parse_external_backend_config()? {
        if pending_full_data_clear.is_some() {
            return Err(
                "Pending full data clear cannot recover through an external backend".to_string(),
            );
        }
        if !wait_for_health(&external, STARTUP_TIMEOUT) {
            return Err("External backend is not ready: /api/health check failed".to_string());
        }

        let mut runtime = state
            .runtime
            .lock()
            .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
        runtime.python_process = None;
        runtime.base_url = Some(external.base_url.clone());
        runtime.session_token = Some(external.session_token.clone());
        runtime.ipc_auth_token = None;
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
    let session_token = api::security::generate_session_token();
    let ipc_auth_token = api::security::generate_session_token();
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
        spawn_dev_backend_pair(
            &ipc_socket_path,
            &ipc_auth_token,
            pending_full_data_clear
                .as_ref()
                .map(|marker| marker.transaction_id.as_str()),
        )?
    } else {
        cleanup_stale_sidecar_processes(&app)?;
        spawn_sidecar_backend(
            &app,
            &ipc_socket_path,
            &ipc_auth_token,
            pending_full_data_clear
                .as_ref()
                .map(|marker| marker.transaction_id.as_str()),
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
    runtime.ipc_auth_token = Some(ipc_auth_token);
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
    let ipc_auth_token = runtime
        .ipc_auth_token
        .clone()
        .ok_or_else(|| "Missing IPC authentication token".to_string())?;

    // Connect IPC client to Python worker (required)
    let ipc_client = match tauri::async_runtime::block_on(ipc::IpcClient::connect(
        &ipc_socket_path,
        &ipc_auth_token,
    )) {
        Ok((client, _event_rx)) => std::sync::Arc::new(client),
        Err(e) => {
            // Kill the process on IPC failure.
            if let Some(mut process) = runtime.python_process.take() {
                process.kill();
            }
            runtime.base_url = None;
            runtime.session_token = None;
            runtime.ipc_auth_token = None;
            runtime.python_pid = None;
            runtime.ipc_socket_path = None;
            runtime.main_port = None;
            return Ok(PollStartupResponse {
                ready: false,
                phase: "error".to_string(),
                error: Some(format!("IPC connect failed: {e}")),
            });
        }
    };

    let security = Arc::new(api::security::GatewaySecurity::new(
        runtime
            .session_token
            .clone()
            .ok_or_else(|| "Backend runtime is missing session token".to_string())?,
    ));
    let api_state = api::state::ApiState::new(ipc_client, security)
        .with_avatar_dirs(resolve_builtin_avatar_dir(&app), resolve_user_avatar_dir());
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
    runtime.ipc_auth_token = None;
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
fn read_backend_startup_diagnostics() -> Result<BackendStartupDiagnosticsResponse, String> {
    let log_path = match current_backend_log_path() {
        Ok(path) => path,
        Err(err) => {
            return Ok(BackendStartupDiagnosticsResponse {
                log_path: None,
                log_excerpt: None,
                log_read_error: Some(err),
            });
        }
    };

    match read_text_file_tail(&log_path, BACKEND_LOG_TAIL_BYTES) {
        Ok(excerpt) => Ok(BackendStartupDiagnosticsResponse {
            log_path: Some(log_path.display().to_string()),
            log_excerpt: if excerpt.trim().is_empty() {
                None
            } else {
                Some(excerpt)
            },
            log_read_error: None,
        }),
        Err(err) => Ok(BackendStartupDiagnosticsResponse {
            log_path: Some(log_path.display().to_string()),
            log_excerpt: None,
            log_read_error: Some(err),
        }),
    }
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

#[tauri::command]
fn begin_full_data_clear(
    state: State<'_, full_data_clear::FullDataClearRuntime>,
) -> Result<full_data_clear::PendingFullDataClear, String> {
    state.begin()
}

#[tauri::command]
fn read_pending_full_data_clear(
    state: State<'_, full_data_clear::FullDataClearRuntime>,
) -> Result<Option<full_data_clear::PendingFullDataClear>, String> {
    state.read()
}

#[tauri::command]
fn complete_full_data_clear(
    state: State<'_, full_data_clear::FullDataClearRuntime>,
    transaction_id: String,
) -> Result<(), String> {
    state.complete(&transaction_id)
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
    let magi_data_root = home_dir()
        .expect("failed to resolve Magi data directory")
        .join(".magi");
    private_data::protect_magi_data_root(&magi_data_root)
        .expect("failed to protect Magi private data");

    let log_dir = desktop_log_dir().expect("failed to resolve desktop log directory");
    let backend_log_path =
        current_backend_log_path().expect("failed to resolve backend log file path");
    let log_level = if cfg!(debug_assertions) {
        log::LevelFilter::Debug
    } else {
        log::LevelFilter::Info
    };
    let desktop_log_runtime = desktop_log_history::DesktopLogRuntime::install(
        log_dir,
        backend_log_path,
        DESKTOP_LOG_MAX_BYTES,
        log_level,
    )
    .expect("failed to initialize desktop logging");
    let full_data_clear_runtime = full_data_clear::FullDataClearRuntime::new(
        full_data_clear_marker_path().expect("failed to resolve full data clear marker path"),
    );

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
        .manage(desktop_log_runtime)
        .manage(full_data_clear_runtime)
        .manage(desktop_presence::DesktopPresenceState::default())
        .setup(move |app| {
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
            start_backend,
            poll_backend_startup,
            stop_backend,
            backend_status,
            get_backend_base_url,
            read_backend_startup_diagnostics,
            set_close_to_tray_enabled,
            set_start_minimized,
            set_skip_quit_confirmation,
            apply_start_minimized,
            confirm_exit_app,
            cancel_exit_request,
            open_url,
            clear_desktop_log_history,
            begin_full_data_clear,
            read_pending_full_data_clear,
            complete_full_data_clear,
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
mod tests {
    #[cfg(windows)]
    use super::plugin_python_candidates_from_resource_dir;
    use super::{
        build_external_backend_config, configure_backend_log_environment,
        configure_full_data_clear_environment, configure_ipc_auth_environment, first_existing_dir,
        isolate_python_worker_environment, ordered_builtin_avatar_dirs,
        plugin_python_path_from_resource_dir, resolve_configured_log_path,
        should_reuse_running_backend, suppress_child_console_window, wait_for_process_stop,
        BackendProcess, BACKEND_LOG_FILE_ENV, DESKTOP_SESSION_TOKEN_ENV,
        FULL_DATA_CLEAR_TRANSACTION_ENV, INTERNAL_IPC_TOKEN_ENV,
    };
    use std::process::{Command, Stdio};
    use std::time::Duration;

    #[test]
    fn external_gateway_config_normalizes_loopback_urls() {
        for (raw, expected_base_url, expected_host, expected_port) in [
            (
                "http://127.0.0.1:19080",
                "http://127.0.0.1:19080/api",
                "127.0.0.1:19080",
                19080,
            ),
            (
                "http://localhost:19080/api/",
                "http://localhost:19080/api",
                "localhost:19080",
                19080,
            ),
        ] {
            let config =
                build_external_backend_config(raw, Some("external-session".to_string())).unwrap();
            assert_eq!(config.base_url, expected_base_url);
            assert_eq!(config.host_header, expected_host);
            assert_eq!(config.port, expected_port);
            assert_eq!(config.session_token, "external-session");
        }
    }

    #[test]
    fn external_gateway_config_rejects_empty_token_and_unsafe_urls() {
        assert!(build_external_backend_config("http://127.0.0.1:19080", None).is_err());
        assert!(
            build_external_backend_config("http://127.0.0.1:19080", Some("   ".to_string()))
                .is_err()
        );

        for raw in [
            "https://127.0.0.1:19080",
            "http://0.0.0.0:19080",
            "http://192.168.1.5:19080",
            "http://[::1]:19080/api",
            "http://127.0.0.1:19080/admin",
            "http://user@127.0.0.1:19080",
            "http://127.0.0.1:0",
        ] {
            assert!(
                build_external_backend_config(raw, Some("external-session".to_string())).is_err(),
                "{raw} must be rejected"
            );
        }
    }

    #[test]
    fn python_worker_command_explicitly_removes_desktop_session_token() {
        let mut command = Command::new("python");
        command.env(DESKTOP_SESSION_TOKEN_ENV, "must-not-leak");
        command.env(INTERNAL_IPC_TOKEN_ENV, "stale-internal-token");
        isolate_python_worker_environment(&mut command);

        assert!(command
            .get_envs()
            .any(|(name, value)| { name == DESKTOP_SESSION_TOKEN_ENV && value.is_none() }));
        assert!(command
            .get_envs()
            .any(|(name, value)| { name == INTERNAL_IPC_TOKEN_ENV && value.is_none() }));
    }

    #[test]
    fn python_worker_receives_only_the_explicit_internal_ipc_token() {
        let mut command = Command::new("python");
        command.env(DESKTOP_SESSION_TOKEN_ENV, "desktop-token");
        isolate_python_worker_environment(&mut command);
        configure_ipc_auth_environment(&mut command, "internal-token");

        assert!(command
            .get_envs()
            .any(|(name, value)| { name == DESKTOP_SESSION_TOKEN_ENV && value.is_none() }));
        assert!(command.get_envs().any(|(name, value)| {
            name == INTERNAL_IPC_TOKEN_ENV && value == Some(std::ffi::OsStr::new("internal-token"))
        }));
    }

    #[test]
    fn pending_full_data_clear_is_forwarded_only_when_present() {
        let mut pending_command = Command::new("python");
        isolate_python_worker_environment(&mut pending_command);
        configure_full_data_clear_environment(
            &mut pending_command,
            Some("clear-restart-transaction"),
        );
        assert!(pending_command.get_envs().any(|(name, value)| {
            name == FULL_DATA_CLEAR_TRANSACTION_ENV
                && value == Some(std::ffi::OsStr::new("clear-restart-transaction"))
        }));

        let mut normal_command = Command::new("python");
        normal_command.env(FULL_DATA_CLEAR_TRANSACTION_ENV, "stale-value");
        isolate_python_worker_environment(&mut normal_command);
        configure_full_data_clear_environment(&mut normal_command, None);
        assert!(normal_command
            .get_envs()
            .any(|(name, value)| { name == FULL_DATA_CLEAR_TRANSACTION_ENV && value.is_none() }));
    }

    #[test]
    fn pending_full_data_clear_forces_a_running_backend_restart() {
        assert!(should_reuse_running_backend(true, false));
        assert!(!should_reuse_running_backend(true, true));
        assert!(!should_reuse_running_backend(false, false));
        assert!(!should_reuse_running_backend(false, true));
    }

    #[test]
    fn backend_log_environment_uses_host_resolved_absolute_paths() {
        let mut command = Command::new("python");
        let backend_log = std::env::temp_dir()
            .join("magi-runtime")
            .join("logs")
            .join("backend.log");

        configure_backend_log_environment(&mut command, &backend_log);

        assert!(command.get_envs().any(|(name, value)| {
            name == BACKEND_LOG_FILE_ENV && value == Some(backend_log.as_os_str())
        }));
    }

    #[test]
    fn relative_backend_log_path_is_resolved_before_worker_chdir() {
        let current_dir = std::env::temp_dir().join("magi-desktop");
        let absolute_log = current_dir.join("absolute-backend-hot.log");

        assert_eq!(
            resolve_configured_log_path(std::path::Path::new("logs/backend-hot.log"), &current_dir,),
            current_dir.join("logs/backend-hot.log"),
        );
        assert_eq!(
            resolve_configured_log_path(&absolute_log, &current_dir),
            absolute_log,
        );
    }

    #[test]
    fn first_existing_dir_returns_first_existing_candidate() {
        let base = std::env::temp_dir().join(format!(
            "magi-first-existing-dir-test-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&base);
        let missing = base.join("missing");
        let first = base.join("first");
        let second = base.join("second");
        std::fs::create_dir_all(&first).unwrap();
        std::fs::create_dir_all(&second).unwrap();

        assert_eq!(
            first_existing_dir([missing, first.clone(), second]),
            Some(first)
        );

        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn builtin_avatar_candidates_prefer_source_tree_in_debug_builds() {
        let base = std::env::temp_dir().join(format!(
            "magi-avatar-candidates-test-{}",
            std::process::id()
        ));
        let source_dir = base
            .join("repo")
            .join("backend")
            .join("personalities")
            .join("avatar");
        let resource_dir = base.join("resource");
        let internal_dir = resource_dir
            .join("sidecar-dist")
            .join("_internal")
            .join("personalities")
            .join("avatar");

        let candidates = ordered_builtin_avatar_dirs(Some(resource_dir), source_dir.clone());

        if cfg!(debug_assertions) {
            assert_eq!(candidates.first(), Some(&source_dir));
        } else {
            assert_eq!(candidates.first(), Some(&internal_dir));
        }
    }

    #[test]
    fn plugin_python_path_uses_bundled_runtime_resource() {
        let resource_dir = std::path::Path::new("/tmp/magi-resources");
        let plugin_python = plugin_python_path_from_resource_dir(resource_dir);

        #[cfg(windows)]
        assert_eq!(
            plugin_python,
            resource_dir.join("plugin-python").join("python.exe")
        );
        #[cfg(windows)]
        let candidates = plugin_python_candidates_from_resource_dir(resource_dir);
        #[cfg(windows)]
        assert!(candidates.contains(
            &resource_dir
                .join("plugin-python")
                .join("Scripts")
                .join("python.exe")
        ));

        #[cfg(not(windows))]
        assert_eq!(
            plugin_python,
            resource_dir
                .join("plugin-python")
                .join("bin")
                .join("python")
        );
    }

    #[test]
    fn read_text_file_tail_skips_truncated_first_line() {
        let base = std::env::temp_dir().join(format!("magi-log-tail-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        let log_path = base.join("backend.log");
        std::fs::write(&log_path, "alpha\nbravo\ncharlie").unwrap();

        let tail = super::read_text_file_tail(&log_path, 12).unwrap();

        assert_eq!(tail, "charlie");

        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn wait_for_process_stop_observes_child_exit() {
        #[cfg(windows)]
        let mut command = {
            let mut command = Command::new("cmd");
            command.args(["/C", "exit", "0"]);
            command
        };
        #[cfg(not(windows))]
        let mut command = {
            let mut command = Command::new("sh");
            command.args(["-c", "exit 0"]);
            command
        };

        suppress_child_console_window(&mut command);
        let child = command
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let pid = Some(child.id());
        let mut process = BackendProcess::Dev(Some(child));

        assert!(wait_for_process_stop(
            &mut process,
            pid,
            Duration::from_secs(2)
        ));
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn parse_sidecar_pids_from_ps_matches_exact_executable_path() {
        let sidecar_path = std::path::Path::new(
            "/Applications/Magi.app/Contents/Resources/sidecar-dist/magi-backend",
        );
        let output = r#"
            101 /Applications/Magi.app/Contents/Resources/sidecar-dist/magi-backend
            102 /Applications/Other.app/Contents/Resources/sidecar-dist/magi-backend
            103 /Applications/Magi.app/Contents/Resources/sidecar-dist/magi-backend-helper
            104 /Applications/Magi.app/Contents/Resources/sidecar-dist/magi-backend
        "#;

        let pids = super::parse_sidecar_pids_from_ps(output, sidecar_path, 104);

        assert_eq!(pids, vec![101]);
    }
}
