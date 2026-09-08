//! Desktop owns only the service child and its lifetime pipe.

use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::time::{Duration, Instant};

use magi_server_runtime::config::ServerConfig;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ListenerInfo {
    base_url: String,
    server_pid: u32,
}

pub struct LocalService {
    child: Child,
    owner: Option<ChildStdin>,
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
        config.validate()?;
        write_config(config_path, config)?;
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|e| e.to_string())?;
        let mut command = Command::new(binary);
        command
            .args(["run", "--config"])
            .arg(config_path)
            .arg("--bootstrap-stdin")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::from(log));
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
            child,
            owner: Some(owner),
            base_url: String::new(),
            session_token: format!(
                "{}{}",
                uuid::Uuid::new_v4().simple(),
                uuid::Uuid::new_v4().simple()
            ),
        };
        let bootstrap = serde_json::json!({"session_token":service.session_token});
        writeln!(
            service
                .owner
                .as_mut()
                .ok_or("Service owner pipe is unavailable")?,
            "{bootstrap}"
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
                    serde_json::from_str::<ListenerInfo>(&line)
                        .map_err(|_| "Service did not report a valid listener".into())
                });
            let _ = sender.send(result);
        });
        let info = receiver
            .recv_timeout(Duration::from_secs(15))
            .map_err(|_| "Service listener startup timed out")??;
        if info.server_pid != service.child.id() {
            return Err("Service process identity does not match".into());
        }
        crate::connections::protocol::CenterClient::local(&info.base_url)?;
        service.base_url = info.base_url;
        Ok(service)
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
        let deadline = Instant::now() + Duration::from_secs(15);
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
        let mut second = LocalService::start(
            &binary,
            &config,
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
