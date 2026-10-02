//! Desktop owns only the service child and its lifetime pipe.

use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use magi_service_contract::config::ServerConfig;
use magi_service_contract::{OwnerBootstrap, StartedServer};

#[derive(Clone)]
struct LaunchSpec {
    binary: PathBuf,
    config: ServerConfig,
    config_path: PathBuf,
    log_path: PathBuf,
}

pub struct LocalService {
    reservation: Arc<magi_platform::instance::InstanceLease>,
    child: Child,
    launch: LaunchSpec,
    owner: Option<ChildStdin>,
    shutdown_timeout: Duration,
    pub base_url: String,
    pub session_token: String,
}

impl LocalService {
    pub fn start(
        binary: &Path,
        config: &ServerConfig,
        config_path: &Path,
        log_path: PathBuf,
    ) -> Result<Self, String> {
        Self::start_cancellable(
            binary,
            config,
            config_path,
            log_path,
            &AtomicBool::new(false),
            None,
        )
    }

    fn start_cancellable(
        binary: &Path,
        config: &ServerConfig,
        config_path: &Path,
        log_path: PathBuf,
        cancelled: &AtomicBool,
        reservation: Option<Arc<magi_platform::instance::InstanceLease>>,
    ) -> Result<Self, String> {
        if cancelled.load(Ordering::Acquire) {
            return Err("Service launch cancelled".into());
        }
        let launch = LaunchSpec {
            binary: binary.into(),
            config: config.clone(),
            config_path: config_path.into(),
            log_path: log_path.clone(),
        };
        config.validate()?;
        let reservation = match reservation {
            Some(lease) => lease,
            None => Arc::new(magi_platform::instance::InstanceLease::runtime_owner(
                &config.data_dir,
            )?),
        };
        wait_for_previous_service(
            &config.data_dir,
            Duration::from_secs(config.owner_shutdown_timeout_secs()),
            cancelled,
        )?;
        write_config(config_path, config)?;
        if cancelled.load(Ordering::Acquire) {
            return Err("Service launch cancelled".into());
        }
        let mut command = Command::new(binary);
        command
            .args(["run", "--config"])
            .arg(config_path)
            .arg("--bootstrap-stdin")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped());
        #[cfg(unix)]
        command
            .arg("--log-file")
            .arg(&log_path)
            .stderr(Stdio::inherit());
        #[cfg(not(unix))]
        {
            let log = OpenOptions::new()
                .create(true)
                .append(true)
                .open(&log_path)
                .map_err(|e| e.to_string())?;
            command.stderr(Stdio::from(log));
        }
        for name in [
            "MAGI_DESKTOP_SESSION_TOKEN",
            "MAGI_IPC_AUTH_TOKEN",
            "MAGI_FULL_DATA_CLEAR_TRANSACTION_ID",
            "MAGI_BACKEND_LOG_FILE",
            "PYTHONPATH",
            "PYTHONHOME",
        ] {
            command.env_remove(name);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let mut child = command
            .spawn()
            .map_err(|e| format!("Could not start Magi service: {e}"))?;
        let owner = child
            .stdin
            .take()
            .ok_or("Service owner pipe is unavailable")?;
        let output = child
            .stdout
            .take()
            .ok_or("Service listener pipe is unavailable")?;
        let mut service = Self {
            reservation,
            child,
            launch,
            owner: Some(owner),
            shutdown_timeout: Duration::from_secs(config.owner_shutdown_timeout_secs()),
            base_url: String::new(),
            session_token: format!(
                "{}{}",
                uuid::Uuid::new_v4().simple(),
                uuid::Uuid::new_v4().simple()
            ),
        };
        let bootstrap = OwnerBootstrap {
            session_token: service.session_token.clone(),
        };
        writeln!(
            service
                .owner
                .as_mut()
                .ok_or("Service owner pipe is unavailable")?,
            "{}",
            serde_json::to_string(&bootstrap).map_err(|e| e.to_string())?
        )
        .map_err(|e| e.to_string())?;
        let (sender, receiver) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let mut line = String::new();
            let result = BufReader::new(output)
                .take(4097)
                .read_line(&mut line)
                .map_err(|_| "Could not read service listener".to_owned())
                .and_then(|_| {
                    if line.len() > 4096 {
                        return Err("Service listener report exceeds size limit".into());
                    }
                    serde_json::from_str::<StartedServer>(&line)
                        .map_err(|_| "Service did not report a valid listener".into())
                });
            let _ = sender.send(result);
        });
        let deadline = Instant::now() + Duration::from_secs(config.listener_startup_timeout_secs());
        let info = loop {
            if cancelled.load(Ordering::Acquire) {
                return Err("Service launch cancelled".into());
            }
            if Instant::now() >= deadline {
                return Err("Service listener startup timed out".into());
            }
            match receiver.recv_timeout(Duration::from_millis(50)) {
                Ok(info) => break info?,
                Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
                Err(_) => return Err("Service listener report was interrupted".into()),
            }
        };
        if info.server_pid != service.child.id() {
            return Err("Service process identity does not match".into());
        }
        crate::connections::protocol::CenterClient::local(&info.base_url)?;
        service.base_url = info.base_url;
        Ok(service)
    }

    /// Reuse the exact launch configuration of this owned service.
    pub fn restart(&self, cancelled: &AtomicBool) -> Result<Self, String> {
        Self::start_cancellable(
            &self.launch.binary,
            &self.launch.config,
            &self.launch.config_path,
            self.launch.log_path.clone(),
            cancelled,
            Some(self.reservation.clone()),
        )
    }

    pub fn supervision_policy(&self) -> &magi_service_contract::lifecycle::SupervisionPolicy {
        &self.launch.config.supervision
    }

    /// Force only this owned child after sustained failed responsiveness probes.
    pub fn terminate_unresponsive(&mut self) {
        self.owner.take();
        let _ = self.child.kill();
        let _ = self.child.wait();
    }

    pub fn pid(&self) -> u32 {
        self.child.id()
    }

    pub fn running(&mut self) -> Result<bool, String> {
        self.child
            .try_wait()
            .map(|status| status.is_none())
            .map_err(|e| e.to_string())
    }

    pub fn stop(&mut self) {
        self.owner.take();
        let deadline = Instant::now() + self.shutdown_timeout;
        while Instant::now() < deadline {
            match self.child.try_wait() {
                Ok(Some(_)) => return,
                Ok(None) => std::thread::sleep(Duration::from_millis(50)),
                Err(_) => break,
            }
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for LocalService {
    fn drop(&mut self) {
        self.stop();
    }
}

fn wait_for_previous_service(
    data_root: &Path,
    timeout: Duration,
    cancelled: &AtomicBool,
) -> Result<(), String> {
    // The previous desktop may exit before its service finishes draining.
    // Keep the new owner lease while waiting; never take over a live service.
    let lease_path = data_root.join("runtime/server.lock");
    let deadline = Instant::now() + timeout;
    let mut reported_wait = false;
    loop {
        if cancelled.load(Ordering::Acquire) {
            return Err("Service launch cancelled".into());
        }
        if !magi_platform::instance::InstanceLease::is_held(&lease_path)? {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err("Previous local service did not finish shutting down before the startup deadline; retry after it exits".into());
        }
        if !reported_wait {
            log::info!("Waiting for the previous local service to finish shutting down");
            reported_wait = true;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

fn write_config(path: &Path, config: &ServerConfig) -> Result<(), String> {
    let temporary = path.with_extension("tmp");
    let mut options = OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
    }
    let mut file = options.open(&temporary).map_err(|e| e.to_string())?;
    file.write_all(&serde_json::to_vec_pretty(config).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    file.sync_all().map_err(|e| e.to_string())?;
    drop(file);
    fs::rename(temporary, path).map_err(|e| e.to_string())
}

pub fn local_data_root() -> Result<PathBuf, String> {
    if let Some(root) = std::env::var_os("MAGI_HOME") {
        return Ok(PathBuf::from(root));
    }
    let home = std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .ok_or("User home directory is unavailable")?;
    Ok(PathBuf::from(home).join(".magi"))
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn waits_for_previous_service_before_spawning_replacement() {
        let root = tempfile::tempdir().unwrap();
        let data = root.path().join("data");
        let previous_owner = magi_platform::instance::InstanceLease::runtime_owner(&data).unwrap();
        let previous_service =
            magi_platform::instance::InstanceLease::acquire(&data.join("runtime/server.lock"))
                .unwrap();
        drop(previous_owner);
        let binary = root.path().join("fake-service");
        fs::write(&binary, "#!/bin/sh\nread bootstrap\nprintf '{\"baseUrl\":\"http://127.0.0.1:19080/api\",\"serverPid\":%s}\\n' \"$$\"\ncat >/dev/null\n").unwrap();
        fs::set_permissions(&binary, fs::Permissions::from_mode(0o700)).unwrap();
        let config = ServerConfig::for_development(root.path(), data.clone());
        let config_path = root.path().join("server.json");
        let log_path = root.path().join("service.log");
        let (sender, receiver) = std::sync::mpsc::channel();
        let launch = std::thread::spawn(move || {
            let result = LocalService::start(&binary, &config, &config_path, log_path);
            let _ = sender.send(result);
        });

        assert!(matches!(
            receiver.recv_timeout(Duration::from_secs(2)),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout)
        ));
        assert!(magi_platform::instance::InstanceLease::runtime_owner(&data).is_err());
        drop(previous_service);
        let mut service = receiver
            .recv_timeout(Duration::from_secs(5))
            .unwrap()
            .unwrap();
        assert!(service.running().unwrap());
        service.stop();
        launch.join().unwrap();
    }

    #[test]
    fn previous_service_wait_times_out_without_releasing_its_lease() {
        let root = tempfile::tempdir().unwrap();
        let _owner = magi_platform::instance::InstanceLease::runtime_owner(root.path()).unwrap();
        let path = root.path().join("runtime/server.lock");
        let _service = magi_platform::instance::InstanceLease::acquire(&path).unwrap();

        let error = wait_for_previous_service(root.path(), Duration::ZERO, &AtomicBool::new(false))
            .unwrap_err();

        assert!(error.contains("Previous local service did not finish shutting down"));
        assert!(magi_platform::instance::InstanceLease::is_held(&path).unwrap());
    }

    #[test]
    fn previous_service_wait_observes_cancellation() {
        let root = tempfile::tempdir().unwrap();
        let _owner = magi_platform::instance::InstanceLease::runtime_owner(root.path()).unwrap();
        let path = root.path().join("runtime/server.lock");
        let _service = magi_platform::instance::InstanceLease::acquire(&path).unwrap();
        let cancelled = Arc::new(AtomicBool::new(false));
        let cancellation = cancelled.clone();
        let data = root.path().to_path_buf();
        let (sender, receiver) = std::sync::mpsc::channel();
        let wait = std::thread::spawn(move || {
            sender
                .send(wait_for_previous_service(
                    &data,
                    Duration::from_secs(5),
                    &cancellation,
                ))
                .unwrap();
        });
        assert!(matches!(
            receiver.recv_timeout(Duration::from_millis(100)),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout)
        ));
        cancelled.store(true, Ordering::Release);

        assert_eq!(
            receiver.recv_timeout(Duration::from_secs(1)).unwrap(),
            Err("Service launch cancelled".into())
        );
        wait.join().unwrap();
        assert!(magi_platform::instance::InstanceLease::is_held(&path).unwrap());
    }

    #[test]
    fn owner_pipe_stops_only_its_own_service() {
        let root =
            std::env::temp_dir().join(format!("magi-host-{}", uuid::Uuid::new_v4().simple()));
        fs::create_dir_all(&root).unwrap();
        let binary = root.join("fake-service");
        fs::write(&binary, "#!/bin/sh\nread bootstrap\nprintf '{\"baseUrl\":\"http://127.0.0.1:19080/api\",\"serverPid\":%s}\\n' \"$$\"\ncat >/dev/null\n").unwrap();
        fs::set_permissions(&binary, fs::Permissions::from_mode(0o700)).unwrap();
        let config = ServerConfig::for_development(&root, root.join("data"));
        let mut first = LocalService::start(
            &binary,
            &config,
            &root.join("first.json"),
            root.join("first.log"),
        )
        .unwrap();
        assert!(LocalService::start(
            &binary,
            &config,
            &root.join("duplicate.json"),
            root.join("duplicate.log")
        )
        .is_err());
        let other_config = ServerConfig::for_development(&root, root.join("other-data"));
        let mut second = LocalService::start(
            &binary,
            &other_config,
            &root.join("second.json"),
            root.join("second.log"),
        )
        .unwrap();
        assert!(first.running().unwrap());
        first.stop();
        assert!(!first.running().unwrap());
        assert!(second.running().unwrap());
        assert!(!fs::read_to_string(root.join("first.json"))
            .unwrap()
            .contains(&first.session_token));
        second.stop();
        fs::remove_dir_all(root).unwrap();
    }
}
