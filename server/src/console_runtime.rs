//! The console owns only services it starts in foreground mode.

use crate::console_api::{management, Request};
use magi_service_contract::config::ServerConfig;
use serde::{Deserialize, Serialize};
use std::{
    path::Path,
    process::{Child, ChildStdin, Command, Stdio},
    time::{Duration, Instant},
};

#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RunMode {
    Foreground,
    Background,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Preferences {
    run_mode: RunMode,
}

pub fn saved_mode(path: &Path) -> Result<Option<RunMode>, String> {
    match std::fs::read(path.with_extension("console.json")) {
        Ok(bytes) => serde_json::from_slice::<Preferences>(&bytes)
            .map(|p| Some(p.run_mode))
            .map_err(|_| "Invalid console run-mode preferences".into()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.to_string()),
    }
}

pub fn save_mode(path: &Path, mode: RunMode) -> Result<(), String> {
    crate::cli::create_private_file(
        &path.with_extension("console.json"),
        &serde_json::to_vec(&Preferences { run_mode: mode }).map_err(|e| e.to_string())?,
    )
}

pub struct Foreground {
    child: Child,
    input: Option<ChildStdin>,
    shutdown_timeout: Duration,
}

impl Foreground {
    pub fn start(path: &Path, config: &ServerConfig) -> Result<Self, String> {
        std::fs::create_dir_all(config.data_dir.join("logs")).map_err(|e| e.to_string())?;
        magi_platform::private_data::protect_magi_data_root(&config.data_dir)?;
        let mut command = Command::new(std::env::current_exe().map_err(|e| e.to_string())?);
        command
            .args(["run", "--config"])
            .arg(path)
            .arg("--shutdown-on-stdin-close")
            .arg("--log-file")
            .arg(config.data_dir.join("logs/service.log"))
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit());
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            // Terminal signals reach the console; closing its pipe drains the owner.
            command.process_group(0);
        }
        let mut child = command.spawn().map_err(|e| e.to_string())?;
        let input = child.stdin.take();
        Ok(Self {
            child,
            input,
            shutdown_timeout: Duration::from_secs(config.owner_shutdown_timeout_secs() + 2),
        })
    }

    pub fn exited(&mut self) -> Result<bool, String> {
        self.child
            .try_wait()
            .map(|status| status.is_some())
            .map_err(|e| e.to_string())
    }

    pub fn wait(mut self) -> Result<(), String> {
        let status = self.child.wait().map_err(|e| e.to_string())?;
        if status.success() {
            Ok(())
        } else {
            Err(format!(
                "Foreground service exited: {status}. Check service.log."
            ))
        }
    }
}

impl Drop for Foreground {
    fn drop(&mut self) {
        self.input.take();
        let deadline = Instant::now() + self.shutdown_timeout;
        while matches!(self.child.try_wait(), Ok(None)) {
            if Instant::now() >= deadline {
                let _ = self.child.kill();
                let _ = self.child.wait();
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }
}

pub fn wait_ready(
    config: &ServerConfig,
    foreground: &mut Option<Foreground>,
) -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(config.startup_timeout_secs + 10);
    loop {
        if let Some(child) = foreground.as_mut() {
            if child.exited()? {
                return Err("Service exited during startup. Check service.log.".into());
            }
        }
        if management(config, Request::Status).is_ok_and(|status| status["service_ready"] == true) {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err("Service setup is not ready. Check status and service.log, then run magi-server again.".into());
        }
        std::thread::sleep(Duration::from_millis(200));
    }
}
