use serde::Serialize;
use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

const BACKEND_HOST: &str = "127.0.0.1";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(25);

#[derive(Default)]
struct BackendState {
    runtime: Mutex<BackendRuntime>,
}

#[derive(Default)]
struct BackendRuntime {
    process: Option<BackendProcess>,
    base_url: Option<String>,
    ws_base_url: Option<String>,
    session_token: Option<String>,
    pid: Option<u32>,
}

struct ExternalBackendConfig {
    host: String,
    port: u16,
    base_url: String,
    ws_base_url: String,
    session_token: String,
}

enum BackendProcess {
    Sidecar(CommandChild),
    Dev(Child),
}

impl BackendProcess {
    fn kill(&mut self) {
        match self {
            Self::Sidecar(child) => {
                let _ = child.kill();
            }
            Self::Dev(child) => {
                let _ = child.kill();
            }
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct StartBackendResponse {
    ok: bool,
    base_url: String,
    ws_base_url: String,
    session_token: String,
    pid: Option<u32>,
    error: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendStatusResponse {
    running: bool,
    base_url: Option<String>,
    ws_base_url: Option<String>,
    pid: Option<u32>,
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
                    && (response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200"))
                {
                    return true;
                }
            }
        }
        thread::sleep(Duration::from_millis(200));
    }
    false
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

    let host = env::var("MAGI_TAURI_EXTERNAL_BACKEND_HOST").unwrap_or_else(|_| BACKEND_HOST.to_string());
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

fn spawn_sidecar(
    app: &AppHandle,
    port: u16,
    session_token: &str,
) -> Result<(BackendProcess, Option<u32>), String> {
    let port_text = port.to_string();
    let (mut rx, child) = app
        .shell()
        .sidecar("magi-backend")
        .map_err(|err| format!("Failed to prepare backend sidecar: {err}"))?
        .args(["--host", BACKEND_HOST, "--port", &port_text, "--no-reload"])
        .env("MAGI_DESKTOP_MODE", "1")
        .env("MAGI_BACKEND_HOST", BACKEND_HOST)
        .env("MAGI_BACKEND_PORT", &port_text)
        .env("MAGI_BACKEND_RELOAD", "0")
        .env("MAGI_DESKTOP_SESSION_TOKEN", session_token)
        .spawn()
        .map_err(|err| format!("Failed to spawn backend sidecar: {err}"))?;

    let pid = child.pid();
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let message = String::from_utf8_lossy(&line).to_string();
                    let _ = app_handle.emit("backend-log", format!("stdout: {}", message.trim_end()));
                }
                CommandEvent::Stderr(line) => {
                    let message = String::from_utf8_lossy(&line).to_string();
                    let _ = app_handle.emit("backend-log", format!("stderr: {}", message.trim_end()));
                }
                CommandEvent::Terminated(payload) => {
                    let _ = app_handle.emit(
                        "backend-exit",
                        format!(
                            "Backend exited (code: {:?}, signal: {:?})",
                            payload.code, payload.signal
                        ),
                    );
                    break;
                }
                _ => {}
            }
        }
    });

    Ok((BackendProcess::Sidecar(child), pid))
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

fn spawn_dev_backend(port: u16, session_token: &str) -> Result<(BackendProcess, Option<u32>), String> {
    let backend_dir = find_backend_dir()?;
    let port_text = port.to_string();

    let mut command = Command::new("python");
    command
        .arg("run_server.py")
        .arg("--host")
        .arg(BACKEND_HOST)
        .arg("--port")
        .arg(&port_text)
        .arg("--no-reload")
        .env("MAGI_DESKTOP_MODE", "1")
        .env("MAGI_BACKEND_HOST", BACKEND_HOST)
        .env("MAGI_BACKEND_PORT", &port_text)
        .env("MAGI_BACKEND_RELOAD", "0")
        .env("MAGI_DESKTOP_SESSION_TOKEN", session_token)
        .current_dir(backend_dir)
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    let child = command
        .spawn()
        .map_err(|err| format!("Failed to spawn backend with python fallback: {err}"))?;
    let pid = Some(child.id());
    Ok((BackendProcess::Dev(child), pid))
}

fn stop_backend_inner(state: &BackendState) -> Result<(), String> {
    let mut runtime = state
        .runtime
        .lock()
        .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
    if let Some(mut process) = runtime.process.take() {
        process.kill();
    }
    runtime.base_url = None;
    runtime.ws_base_url = None;
    runtime.session_token = None;
    runtime.pid = None;
    Ok(())
}

#[tauri::command]
fn start_backend(app: AppHandle, state: State<'_, BackendState>) -> Result<StartBackendResponse, String> {
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
                pid: runtime.pid,
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
        runtime.process = None;
        runtime.base_url = Some(external.base_url.clone());
        runtime.ws_base_url = Some(external.ws_base_url.clone());
        runtime.session_token = Some(external.session_token.clone());
        runtime.pid = None;

        return Ok(StartBackendResponse {
            ok: true,
            base_url: external.base_url,
            ws_base_url: external.ws_base_url,
            session_token: external.session_token,
            pid: None,
            error: None,
        });
    }

    let port = pick_open_port()?;
    let session_token = generate_session_token();
    let base_url = format!("http://{}:{}/api", BACKEND_HOST, port);
    let ws_base_url = format!("ws://{}:{}", BACKEND_HOST, port);

    let (process, pid) = match spawn_sidecar(&app, port, &session_token) {
        Ok(result) => result,
        Err(sidecar_err) => {
            if cfg!(debug_assertions) {
                spawn_dev_backend(port, &session_token)
                    .map_err(|dev_err| format!("{}; fallback failed: {}", sidecar_err, dev_err))?
            } else {
                return Err(sidecar_err);
            }
        }
    };

    let mut process = process;
    if !wait_for_health(BACKEND_HOST, port, STARTUP_TIMEOUT) {
        process.kill();
        return Err("Backend startup timeout: /api/health did not become ready".to_string());
    }

    let mut runtime = state
        .runtime
        .lock()
        .map_err(|_| "Failed to acquire backend runtime lock".to_string())?;
    runtime.process = Some(process);
    runtime.base_url = Some(base_url.clone());
    runtime.ws_base_url = Some(ws_base_url.clone());
    runtime.session_token = Some(session_token.clone());
    runtime.pid = pid;

    Ok(StartBackendResponse {
        ok: true,
        base_url,
        ws_base_url,
        session_token,
        pid,
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
        pid: runtime.pid,
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

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState::default())
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state: State<'_, BackendState> = window.state();
                let _ = stop_backend_inner(&state);
            }
        })
        .invoke_handler(tauri::generate_handler![
            start_backend,
            stop_backend,
            backend_status,
            get_backend_base_url
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Magi desktop application");
}
