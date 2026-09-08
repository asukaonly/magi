use std::fs::{self, OpenOptions};
use std::process::Stdio;
use std::sync::{atomic::Ordering, Arc};
use std::time::{Duration, Instant};

use magi_gateway::{
    api,
    ipc::{IpcClient, RuntimeConnection},
};
use serde::Serialize;
use tokio::process::{Child, Command};
use tokio::sync::{oneshot, watch};

use crate::{config::ServerConfig, instance::InstanceLease};

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StartedServer {
    pub base_url: String,
    pub server_pid: u32,
}

/// Run one gateway and supervised worker for a private data root.
pub async fn run(
    config: ServerConfig,
    security: Arc<api::security::GatewaySecurity>,
    mut shutdown: watch::Receiver<bool>,
    started: oneshot::Sender<StartedServer>,
) -> Result<(), String> {
    config.validate()?;
    if magi_gateway::db::configured_magi_base_dir()? != config.data_dir {
        return Err("MAGI_HOME must match server configuration before starting the runtime".into());
    }
    magi_platform::private_data::protect_magi_data_root(&config.data_dir)?;
    let runtime_dir = config.data_dir.join("runtime");
    fs::create_dir_all(&runtime_dir)
        .map_err(|e| format!("Failed to create runtime directory: {e}"))?;
    fs::create_dir_all(config.data_dir.join("logs"))
        .map_err(|e| format!("Failed to create logs: {e}"))?;
    magi_platform::private_data::protect_magi_data_root(&config.data_dir)?;
    let _lease = InstanceLease::acquire(&runtime_dir.join("server.lock"))?;
    // A previous supervisor can disappear before its worker releases the data root.
    drop(InstanceLease::acquire(&runtime_dir.join("worker.lock"))?);
    let socket = ipc_address(&config)?;

    let connection = Arc::new(RuntimeConnection::default());
    let state = api::state::ApiState::with_runtime(Arc::clone(&connection), security)
        .with_avatar_dirs(
            config.builtin_avatar_dir.clone(),
            Some(config.data_dir.join("personalities/avatar")),
        );
    let storage_ready = Arc::clone(&state.storage_ready);
    let router = api::build_router(state);
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", config.port))
        .await
        .map_err(|e| format!("Failed to bind server listener: {e}"))?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    let (http_stop_tx, mut http_stop_rx) = watch::channel(false);
    let mut http_task = tokio::spawn(async move {
        magi_gateway::axum::serve(listener, router)
            .with_graceful_shutdown(async move {
                let _ = http_stop_rx.changed().await;
            })
            .await
    });
    let _ = started.send(StartedServer {
        base_url: format!("http://127.0.0.1:{port}/api"),
        server_pid: std::process::id(),
    });
    let mut attempts = 0;
    let result = loop {
        if *shutdown.borrow() {
            break Ok(());
        }
        if http_task.is_finished() {
            break Err("Server listener stopped unexpectedly".into());
        }
        let token = api::security::generate_session_token();
        let _ = fs::remove_file(runtime_dir.join("worker.ready"));
        #[cfg(unix)]
        let _ = fs::remove_file(&socket);
        eprintln!("Starting Python runtime (attempt {})", attempts + 1);
        match WorkerProcess::spawn(&config, &socket, &token) {
            Ok(mut worker) => {
                let outcome = run_worker(
                    &config,
                    &mut worker,
                    &socket,
                    &token,
                    &connection,
                    &storage_ready,
                    &mut shutdown,
                )
                .await;
                storage_ready.store(false, Ordering::Release);
                connection.replace(None);
                worker
                    .stop(Duration::from_secs(config.shutdown_timeout_secs))
                    .await;
                if let Err(error) = outcome {
                    eprintln!("Python runtime unavailable: {error}");
                }
            }
            Err(error) => eprintln!("Python runtime could not start: {error}"),
        }
        if *shutdown.borrow() {
            break Ok(());
        }
        if attempts >= config.max_restarts {
            eprintln!("Python restart limit reached; gateway remains available for diagnostics");
            let _ = shutdown.changed().await;
            break Ok(());
        }
        attempts += 1;
        tokio::select! {
            _ = shutdown.changed() => break Ok(()),
            _ = tokio::time::sleep(Duration::from_secs(1u64 << attempts.min(4))) => {},
        }
    };
    storage_ready.store(false, Ordering::Release);
    connection.replace(None);
    http_stop_tx.send_replace(true);
    if tokio::time::timeout(
        Duration::from_secs(config.shutdown_timeout_secs),
        &mut http_task,
    )
    .await
    .is_err()
    {
        http_task.abort();
        let _ = http_task.await;
    }
    let _ = fs::remove_file(runtime_dir.join("worker.ready"));
    #[cfg(unix)]
    let _ = fs::remove_file(&socket);
    result
}

async fn run_worker(
    config: &ServerConfig,
    worker: &mut WorkerProcess,
    socket: &str,
    token: &str,
    connection: &Arc<RuntimeConnection>,
    storage_ready: &std::sync::atomic::AtomicBool,
    shutdown: &mut watch::Receiver<bool>,
) -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(config.startup_timeout_secs);
    let mut connected = false;
    loop {
        if *shutdown.borrow() {
            return Ok(());
        }
        if let Some(status) = worker.child.try_wait().map_err(|e| e.to_string())? {
            return Err(format!("Python runtime exited ({status})"));
        }
        if !connected {
            let ready = fs::read_to_string(config.data_dir.join("runtime/worker.ready")).ok();
            if ready.as_deref().and_then(|s| s.trim().parse::<u32>().ok()) == Some(worker.pid) {
                let (client, mut events) = IpcClient::connect(socket, token).await?;
                connection.replace(Some(Arc::new(client)));
                tokio::task::spawn_blocking(magi_gateway::db::ensure_indexes)
                    .await
                    .map_err(|e| e.to_string())?;
                storage_ready.store(true, Ordering::Release);
                tokio::spawn(async move { while events.recv().await.is_some() {} });
                connected = true;
                eprintln!("Python runtime connected (pid {})", worker.pid);
            } else if Instant::now() >= deadline {
                return Err("Python runtime startup timed out".into());
            }
        } else if connection.current().is_err() {
            return Err("Python IPC connection closed".into());
        }
        tokio::select! {
            _ = shutdown.changed() => return Ok(()),
            _ = tokio::time::sleep(Duration::from_millis(200)) => {},
        }
    }
}

fn ipc_address(config: &ServerConfig) -> Result<String, String> {
    #[cfg(unix)]
    {
        let path = config
            .data_dir
            .join(format!("runtime/ipc-{}.sock", std::process::id()));
        if path.as_os_str().len() > 100 {
            return Err("Data directory is too long for a Unix socket path".into());
        }
        Ok(path.to_string_lossy().into_owned())
    }
    #[cfg(not(unix))]
    {
        let _ = config;
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).map_err(|e| e.to_string())?;
        Ok(listener
            .local_addr()
            .map_err(|e| e.to_string())?
            .to_string())
    }
}

struct WorkerProcess {
    child: Child,
    pid: u32,
    #[cfg(windows)]
    job: crate::windows_job::WorkerJob,
}

impl WorkerProcess {
    fn spawn(config: &ServerConfig, socket: &str, token: &str) -> Result<Self, String> {
        let log_path = config.data_dir.join("logs/backend.log");
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|e| e.to_string())?;
        let stderr = log.try_clone().map_err(|e| e.to_string())?;
        let mut command = Command::new(&config.worker.executable);
        command
            .args(&config.worker.args)
            .env("MAGI_HOME", &config.data_dir)
            .env("MAGI_IPC_SOCKET", socket)
            .env("MAGI_IPC_AUTH_TOKEN", token)
            .env("MAGI_PLUGIN_PYTHON", &config.worker.plugin_python)
            .env("MAGI_SERVER_PARENT_PID", std::process::id().to_string())
            .env("MAGI_BACKEND_LOG_FILE", &log_path)
            .env_remove("MAGI_DESKTOP_SESSION_TOKEN")
            .env_remove("MAGI_EXTERNAL_BACKEND_SESSION_TOKEN")
            .env_remove("MAGI_FULL_DATA_CLEAR_TRANSACTION_ID")
            .stdin(Stdio::piped())
            .stdout(Stdio::from(log))
            .stderr(Stdio::from(stderr))
            .kill_on_drop(true);
        if let Some(cwd) = &config.worker.working_directory {
            command.current_dir(cwd);
        }
        if !config.worker.python_path.is_empty() {
            command.env(
                "PYTHONPATH",
                std::env::join_paths(&config.worker.python_path).map_err(|e| e.to_string())?,
            );
        } else {
            command.env_remove("PYTHONPATH");
        }
        #[cfg(unix)]
        command.process_group(0);
        #[cfg(windows)]
        command.creation_flags(0x08000000);
        let child = command
            .spawn()
            .map_err(|e| format!("Failed to spawn Python: {e}"))?;
        let pid = child.id().ok_or("Python process has no PID")?;
        #[cfg(windows)]
        let job = crate::windows_job::WorkerJob::attach(&child)?;
        Ok(Self {
            child,
            pid,
            #[cfg(windows)]
            job,
        })
    }

    async fn stop(&mut self, timeout: Duration) {
        // EOF asks the Python launcher to drain, on both Unix and Windows.
        self.child.stdin.take();
        if tokio::time::timeout(timeout, self.child.wait())
            .await
            .is_err()
        {
            #[cfg(windows)]
            self.job.terminate();
            #[cfg(unix)]
            unsafe {
                libc::kill(-(self.pid as i32), libc::SIGKILL);
            }
            let _ = self.child.start_kill();
            let _ = self.child.wait().await;
        }
    }
}

impl Drop for WorkerProcess {
    fn drop(&mut self) {
        #[cfg(unix)]
        unsafe {
            libc::kill(-(self.pid as i32), libc::SIGKILL);
        }
    }
}
