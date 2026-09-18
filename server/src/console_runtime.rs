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
    crate::cli::replace_private_file(
        &path.with_extension("console.json"),
        &serde_json::to_vec(&Preferences { run_mode: mode }).map_err(|e| e.to_string())?,
    )
}

pub struct Foreground {
    data_dir: std::path::PathBuf,
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
            data_dir: config.data_dir.clone(),
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

    pub fn owns(&self, config: &ServerConfig) -> bool {
        self.data_dir == config.data_dir
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
    mut report: impl FnMut(String),
) -> Result<(), String> {
    let started = Instant::now();
    let timeout = Duration::from_secs(config.startup_timeout_secs + 10);
    loop {
        if let Some(child) = foreground.as_mut() {
            child.check_running()?;
        }
        let detail = match management(config, Request::Status) {
            Ok(status) if matches!(status["supervisor"]["phase"].as_str(), Some("failed" | "stopping")) => {
                return Err(format!("Configuration service cannot become ready: runtime is {}. {} Check service.log before retrying.",
                    status["supervisor"]["phase"].as_str().unwrap_or("unavailable"),
                    status["supervisor"]["last_error"].as_str().unwrap_or("")));
            },
            Ok(status) if status["service_ready"] == true => return Ok(()),
            Ok(status) => format!(
                "Local management responds, but the configuration service is not ready. Supervisor phase: {}.",
                status["supervisor"]["phase"].as_str().unwrap_or("unknown")
            ),
            Err(error) => format!("Local management is unavailable: {error}"),
        };
        let progress = if detail.starts_with("Local management is unavailable") {
            "Starting the service"
        } else {
            "Starting the configuration runtime"
        };
        report(format!(
            "Waiting {}s / {}s — {progress}",
            started.elapsed().as_secs(),
            timeout.as_secs()
        ));
        if started.elapsed() >= timeout {
            return Err(format!(
                "Service setup timed out.\n{detail}\nManagement socket: {}\nService log: {}\nFor a background deployment, run magi-server restart with the same --config path, then retry setup. Stop the service before moving or removing its data directories.",
                config.data_dir.join("runtime/manage.sock").display(),
                config.data_dir.join("logs/service.log").display(),
            ));
        }
        std::thread::sleep(Duration::from_millis(500));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(unix)]
    #[test]
    fn readiness_timeout_reports_the_missing_management_channel() {
        let root = std::env::temp_dir().join(format!("magi-console-{}", uuid::Uuid::new_v4()));
        let mut config = ServerConfig::for_bundle(&root.join("bundle"), root.join("data"));
        config.startup_timeout_secs = 1;
        let mut progress = Vec::new();
        let error = wait_ready(&config, &mut None, |detail| progress.push(detail)).unwrap_err();
        assert!(progress.first().unwrap().contains("Waiting 0s / 11s"));
        assert!(error.contains("Local management is unavailable"));
        assert!(error.contains("Cannot connect to running service"));
        assert!(error.contains(
            &config
                .data_dir
                .join("runtime/manage.sock")
                .display()
                .to_string()
        ));
        assert!(error.contains(
            &config
                .data_dir
                .join("logs/service.log")
                .display()
                .to_string()
        ));
        assert!(error.contains("magi-server restart"));
        assert!(!root.exists());
    }

    #[cfg(unix)]
    #[test]
    fn failed_runtime_returns_without_waiting_for_the_startup_deadline() {
        use std::io::{BufRead, BufReader, Write};
        let root =
            std::env::temp_dir().join(format!("mc-{}", &uuid::Uuid::new_v4().to_string()[..8]));
        let config = ServerConfig::for_bundle(&root.join("bundle"), root.join("data"));
        std::fs::create_dir_all(config.data_dir.join("runtime")).unwrap();
        let socket =
            std::os::unix::net::UnixListener::bind(config.data_dir.join("runtime/manage.sock"))
                .unwrap();
        let server = std::thread::spawn(move || {
            let (stream, _) = socket.accept().unwrap();
            let mut stream = BufReader::new(stream);
            let mut line = String::new();
            stream.read_line(&mut line).unwrap();
            writeln!(stream.get_mut(), "{}", serde_json::json!({"success":true,"data":{
                "service_ready":false,"supervisor":{"phase":"failed","last_error":"Fixture worker failure"}
            }})).unwrap();
        });
        let started = Instant::now();
        let error = wait_ready(&config, &mut None, |_| {}).unwrap_err();
        assert!(started.elapsed() < Duration::from_secs(5));
        assert!(error.contains("Fixture worker failure"));
        server.join().unwrap();
        std::fs::remove_dir_all(root).unwrap();
    }

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
