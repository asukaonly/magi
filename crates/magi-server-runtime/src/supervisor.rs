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
    owner_token: Option<String>,
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
    let service_dir = config.data_dir.join("service");
    fs::create_dir_all(&service_dir).map_err(|e| e.to_string())?;
    let auth = Arc::new(magi_gateway::auth::AuthStore::open(
        &service_dir.join("server.db"),
    )?);
    if let Some(token) = owner_token {
        auth.bootstrap_local_owner(&token);
    }
    magi_platform::private_data::protect_magi_data_root(&config.data_dir)?;
    let security = Arc::new(api::security::GatewaySecurity::with_auth(Arc::clone(&auth)));
    let socket = ipc_address(&config)?;

    let connection = Arc::new(RuntimeConnection::default());
    let mut state =
        api::state::ApiState::with_runtime(Arc::clone(&connection), Arc::clone(&security))
            .with_avatar_dirs(
                config.builtin_avatar_dir.clone(),
                Some(config.data_dir.join("personalities/avatar")),
            );
    let storage_ready = Arc::clone(&state.storage_ready);
    let events = Arc::clone(&state.events);
    let maintenance = Arc::new(crate::maintenance::Coordinator::open(
        &config.data_dir,
        &auth.server_id,
        Arc::clone(&storage_ready),
        Arc::clone(&events),
        Arc::clone(&security),
    )?);
    state.maintenance = Some(maintenance.clone());
    let router = api::build_router(state);
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", config.port))
        .await
        .map_err(|e| format!("Failed to bind server listener: {e}"))?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    #[cfg(unix)]
    let _management = crate::management::ManagementServer::bind(
        &config.data_dir,
        auth,
        Arc::clone(&storage_ready),
        format!("http://127.0.0.1:{port}/api"),
        shutdown.clone(),
    )?;
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
    let event_hub = Arc::clone(&events);
    let emitter: magi_gateway::notification_bridge::EventEmitFn =
        Arc::new(move |event, payload| {
            if event == "server_resync_required" {
                event_hub.reset("notification_source_changed");
            } else {
                event_hub.publish(
                    "runtime.notification",
                    serde_json::to_value(payload).unwrap_or_default(),
                );
            }
        });
    let bridge_shutdown = shutdown.clone();
    let bridge = tokio::spawn(async move {
        magi_gateway::notification_bridge::run_notification_bridge(Some(emitter), bridge_shutdown)
            .await;
    });
    let mut attempts = 0;
    let result = loop {
        use magi_gateway::maintenance::MaintenanceControl;
        if *shutdown.borrow() {
            break Ok(());
        }
        if http_task.is_finished() {
            break Err("Server listener stopped unexpectedly".into());
        }
        if maintenance.status().phase == "failed" {
            tokio::select! {
                _ = shutdown.changed() => break Ok(()),
                _ = maintenance.changed.notified() => {},
            }
            continue;
        }
        let recovery = maintenance.pending();
        if recovery.is_none() && maintenance.is_active() {
            tokio::select! { _ = shutdown.changed() => break Ok(()), _ = maintenance.changed.notified() => {} }
            continue;
        }
        let database_drain = if recovery.is_some() {
            maintenance.set_phase("draining", None);
            match tokio::time::timeout(
                Duration::from_secs(30),
                magi_gateway::database_gate::global().drain(),
            )
            .await
            {
                Ok(Ok(guard)) => Some(guard),
                _ => {
                    maintenance
                        .set_phase("failed", Some("Native database work did not drain".into()));
                    continue;
                }
            }
        } else {
            None
        };
        let token = api::security::generate_session_token();
        let _ = fs::remove_file(runtime_dir.join("worker.ready"));
        #[cfg(unix)]
        let _ = fs::remove_file(&socket);
        eprintln!("Starting Python runtime (attempt {})", attempts + 1);
        let mut planned_restart = false;
        match WorkerProcess::spawn(
            &config,
            &socket,
            &token,
            recovery
                .as_ref()
                .map(|marker| marker.transaction_id.as_str()),
        ) {
            Ok(mut worker) => {
                let mut context = WorkerContext {
                    config: &config,
                    socket: &socket,
                    connection: &connection,
                    storage_ready: &storage_ready,
                    events: &events,
                    maintenance: &maintenance,
                    shutdown: &mut shutdown,
                };
                let outcome =
                    run_worker(&mut context, &mut worker, &token, recovery.as_ref()).await;
                storage_ready.store(false, Ordering::Release);
                events.reset("runtime_unavailable");
                connection.replace(None);
                worker
                    .stop(Duration::from_secs(config.shutdown_timeout_secs))
                    .await;
                match outcome {
                    Ok(WorkerExit::Maintenance) => {
                        planned_restart = true;
                    }
                    Ok(WorkerExit::Cleared(result)) => {
                        let id = &recovery
                            .as_ref()
                            .expect("clear recovery owner")
                            .transaction_id;
                        let logs = config.data_dir.join("logs");
                        let completed = async {
                            tokio::task::spawn_blocking(move || clear_server_logs(&logs))
                                .await
                                .map_err(|e| e.to_string())??;
                            maintenance.complete(id, result).await
                        }
                        .await;
                        match completed {
                            Ok(()) => {
                                planned_restart = true;
                            }
                            Err(error) => maintenance.set_phase("failed", Some(error)),
                        }
                    }
                    Ok(WorkerExit::Stopped) => {}
                    Err(error) => {
                        if recovery.is_some() {
                            maintenance.set_phase("failed", Some(error));
                        } else {
                            eprintln!("Python runtime unavailable: {error}");
                        }
                    }
                }
            }
            Err(error) => {
                if recovery.is_some() {
                    maintenance.set_phase("failed", Some(error));
                } else {
                    eprintln!("Python runtime could not start: {error}");
                }
            }
        }
        drop(database_drain);
        if !maintenance.is_active() {
            magi_gateway::database_gate::global().reopen();
        }
        if *shutdown.borrow() {
            break Ok(());
        }
        if planned_restart {
            attempts = 0;
            continue;
        }
        if maintenance.pending().is_some() {
            continue;
        }
        if attempts >= config.max_restarts {
            eprintln!("Python restart limit reached; gateway remains available for diagnostics");
            tokio::select! {
                _ = shutdown.changed() => break Ok(()),
                _ = maintenance.changed.notified() => { attempts = 0; continue; },
            }
        }
        attempts += 1;
        tokio::select! {
            _ = shutdown.changed() => break Ok(()),
            _ = tokio::time::sleep(Duration::from_secs(1u64 << attempts.min(4))) => {},
            _ = maintenance.changed.notified() => {},
        }
    };
    storage_ready.store(false, Ordering::Release);
    connection.replace(None);
    bridge.abort();
    let _ = bridge.await;
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

enum WorkerExit {
    Stopped,
    Maintenance,
    Cleared(serde_json::Value),
}

struct WorkerContext<'a> {
    config: &'a ServerConfig,
    socket: &'a str,
    connection: &'a Arc<RuntimeConnection>,
    storage_ready: &'a std::sync::atomic::AtomicBool,
    events: &'a magi_gateway::events::EventHub,
    maintenance: &'a crate::maintenance::Coordinator,
    shutdown: &'a mut watch::Receiver<bool>,
}

async fn run_worker(
    context: &mut WorkerContext<'_>,
    worker: &mut WorkerProcess,
    token: &str,
    recovery: Option<&magi_platform::full_data_clear::PendingFullDataClear>,
) -> Result<WorkerExit, String> {
    let deadline = Instant::now() + Duration::from_secs(context.config.startup_timeout_secs);
    let mut connected = false;
    loop {
        if *context.shutdown.borrow() {
            return Ok(WorkerExit::Stopped);
        }
        if recovery.is_none() && context.maintenance.is_active() {
            return Ok(WorkerExit::Maintenance);
        }
        if let Some(status) = worker.child.try_wait().map_err(|e| e.to_string())? {
            return Err(format!("Python runtime exited ({status})"));
        }
        if !connected {
            let ready =
                fs::read_to_string(context.config.data_dir.join("runtime/worker.ready")).ok();
            if ready
                .as_deref()
                .and_then(|value| value.trim().parse::<u32>().ok())
                == Some(worker.pid)
            {
                let (client, mut ipc_events) = IpcClient::connect(context.socket, token).await?;
                let client = Arc::new(client);
                context.connection.replace(Some(Arc::clone(&client)));
                if let Some(recovery) = recovery {
                    context.maintenance.set_phase("clearing", None);
                    let result = tokio::select! {
                        _ = context.shutdown.changed() => return Ok(WorkerExit::Stopped),
                        result = client.request_with_timeout("api.forward", Some(serde_json::json!({
                            "method":"DELETE", "path":"/api/memory/clear", "query":{},
                            "headers":{"x-magi-full-clear-transaction":recovery.transaction_id}, "body":null
                        })), Duration::from_secs(600)) => result.map_err(|e| e.to_string())?,
                    };
                    if result["status"] != 200 || result["body"]["success"] != true {
                        return Err(
                            "Python full clear remains incomplete; retry this operation".into()
                        );
                    }
                    return Ok(WorkerExit::Cleared(result["body"].clone()));
                }
                if context.maintenance.is_active() {
                    return Ok(WorkerExit::Maintenance);
                }
                if context.maintenance.is_active() {
                    return Ok(WorkerExit::Maintenance);
                }
                context.storage_ready.store(true, Ordering::Release);
                context
                    .events
                    .publish("state.changed", serde_json::json!({"resource":"runtime"}));
                tokio::spawn(async move { while ipc_events.recv().await.is_some() {} });
                connected = true;
                eprintln!("Python runtime connected (pid {})", worker.pid);
            } else if Instant::now() >= deadline {
                return Err("Python runtime startup timed out".into());
            }
        } else if context.connection.current().is_err() {
            return Err("Python IPC connection closed".into());
        }
        tokio::select! {
            _ = context.shutdown.changed() => return Ok(WorkerExit::Stopped),
            _ = tokio::time::sleep(Duration::from_millis(200)) => {},
            _ = context.maintenance.changed.notified(), if recovery.is_none() => {},
        }
    }
}

fn clear_server_logs(directory: &std::path::Path) -> Result<(), String> {
    for entry in fs::read_dir(directory).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        let metadata = entry.file_type().map_err(|e| e.to_string())?;
        if !metadata.is_file() {
            return Err("Unexpected entry in server log directory".into());
        }
        let mut options = OpenOptions::new();
        options.write(true).truncate(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.custom_flags(libc::O_NOFOLLOW);
        }
        let file = options.open(entry.path()).map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
    }
    Ok(())
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
    fn spawn(
        config: &ServerConfig,
        socket: &str,
        token: &str,
        clear_id: Option<&str>,
    ) -> Result<Self, String> {
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
        if let Some(clear_id) = clear_id {
            command.env("MAGI_FULL_DATA_CLEAR_TRANSACTION_ID", clear_id);
        }
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
