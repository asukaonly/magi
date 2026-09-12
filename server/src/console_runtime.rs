//! The console owns only services it starts in foreground mode.

use crate::console_api::{management, Request};
use magi_service_contract::config::ServerConfig;
use serde::{Deserialize, Serialize};
use std::{
    collections::VecDeque,
    io::Read,
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
    diagnostics: Option<std::thread::JoinHandle<std::io::Result<String>>>,
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
            .stderr(Stdio::piped());
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            // Terminal signals reach the console; closing its pipe drains the owner.
            command.process_group(0);
        }
        let mut child = command.spawn().map_err(|e| e.to_string())?;
        let input = child.stdin.take();
        let mut foreground = Self {
            child,
            input,
            shutdown_timeout: Duration::from_secs(config.owner_shutdown_timeout_secs() + 2),
            diagnostics: None,
        };
        let stderr = foreground
            .child
            .stderr
            .take()
            .ok_or("Service error output is unavailable")?;
        foreground.diagnostics = Some(
            std::thread::Builder::new()
                .name("magi-console-diagnostics".into())
                .spawn(move || capture_diagnostics(stderr))
                .map_err(|e| e.to_string())?,
        );
        Ok(foreground)
    }

    pub fn check_running(&mut self) -> Result<(), String> {
        if let Some(status) = self.child.try_wait().map_err(|e| e.to_string())? {
            return Err(self.exit_error(status));
        }
        Ok(())
    }

    fn exit_error(&mut self, status: std::process::ExitStatus) -> String {
        let diagnostics = self
            .diagnostics
            .take()
            .and_then(|reader| reader.join().ok())
            .and_then(Result::ok)
            .unwrap_or_default();
        let mut error = format!("Foreground service exited: {status}. Check service.log.");
        if !diagnostics.trim().is_empty() {
            error.push_str("\nStartup diagnostics:\n");
            error.extend(
                diagnostics
                    .trim()
                    .chars()
                    .filter(|c| !c.is_control() || *c == '\n'),
            );
        }
        error
    }

    pub fn wait(mut self) -> Result<(), String> {
        let status = self.child.wait().map_err(|e| e.to_string())?;
        if status.success() {
            Ok(())
        } else {
            Err(self.exit_error(status))
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
        if let Some(reader) = self.diagnostics.take() {
            let _ = reader.join();
        }
    }
}

fn capture_diagnostics(mut source: impl Read) -> std::io::Result<String> {
    // Service logs go to files. Capture pre-log startup errors without sharing the terminal.
    let mut tail = VecDeque::with_capacity(8192);
    let mut buffer = [0; 4096];
    loop {
        match source.read(&mut buffer) {
            Ok(0) => {
                return Ok(
                    String::from_utf8_lossy(&tail.into_iter().collect::<Vec<_>>()).into_owned(),
                )
            }
            Ok(count) => {
                let discard = (tail.len() + count).saturating_sub(8192);
                tail.drain(..discard);
                tail.extend(&buffer[..count]);
            }
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
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
            child.check_running()?;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn startup_diagnostics_are_drained_without_unbounded_retention() {
        let bytes = format!("{}final startup failure", "x".repeat(32_768));
        let mut source = std::io::Cursor::new(bytes.as_bytes());
        let tail = capture_diagnostics(&mut source).unwrap();
        assert_eq!(source.position(), bytes.len() as u64);
        assert_eq!(tail.len(), 8192);
        assert!(tail.ends_with("final startup failure"));
    }
}
