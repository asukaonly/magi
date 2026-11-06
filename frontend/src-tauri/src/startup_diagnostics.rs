//! A launch owns its report, so late work cannot overwrite a later attempt.

use serde::Serialize;
use std::fs::{self, File, Metadata};
use std::io::{Read, Seek, SeekFrom};
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

const LOG_LIMIT: u64 = 65_536;

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StartupReport {
    pub attempt_id: String,
    pub app_version: String,
    pub os_name: String,
    pub os_version: Option<String>,
    pub architecture: String,
    pub mode: Option<String>,
    pub phase: String,
    pub started_at_ms: u64,
    pub failed_at_ms: Option<u64>,
    pub duration_ms: u64,
    pub process_id: Option<u32>,
    pub exit_code: Option<i32>,
    pub failure_message: Option<String>,
    pub log_path: Option<String>,
    pub log_excerpt: Option<String>,
    pub log_excerpt_scope: Option<String>,
    pub log_excerpt_truncated: bool,
    pub log_read_error: Option<String>,
}

#[derive(Clone, PartialEq)]
struct FileIdentity {
    created: Option<SystemTime>,
    #[cfg(unix)]
    device: u64,
    #[cfg(unix)]
    inode: u64,
}

impl FileIdentity {
    fn of(metadata: &Metadata) -> Self {
        #[cfg(unix)]
        use std::os::unix::fs::MetadataExt;
        Self {
            created: metadata.created().ok(),
            #[cfg(unix)]
            device: metadata.dev(),
            #[cfg(unix)]
            inode: metadata.ino(),
        }
    }
}

#[derive(Clone)]
struct LogBoundary {
    path: PathBuf,
    offset: Option<u64>,
    identity: Option<FileIdentity>,
}

pub struct StartupAttempt {
    started: Instant,
    state: Mutex<(StartupReport, Option<LogBoundary>)>,
}

impl StartupAttempt {
    pub fn new(mode: Option<&str>) -> Self {
        Self {
            started: Instant::now(),
            state: Mutex::new((
                StartupReport {
                    attempt_id: uuid::Uuid::new_v4().to_string(),
                    app_version: env!("CARGO_PKG_VERSION").into(),
                    os_name: std::env::consts::OS.into(),
                    os_version: None,
                    architecture: std::env::consts::ARCH.into(),
                    mode: mode.map(str::to_owned),
                    phase: "connecting".into(),
                    started_at_ms: timestamp(),
                    failed_at_ms: None,
                    duration_ms: 0,
                    process_id: None,
                    exit_code: None,
                    failure_message: None,
                    log_path: None,
                    log_excerpt: None,
                    log_excerpt_scope: None,
                    log_excerpt_truncated: false,
                    log_read_error: None,
                },
                None,
            )),
        }
    }

    pub fn mode(&self, mode: &str) {
        self.state.lock().unwrap_or_else(|e| e.into_inner()).0.mode = Some(mode.into());
    }

    pub fn phase(&self, phase: &str) {
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        if state.0.failed_at_ms.is_none() {
            state.0.phase = phase.into();
            state.0.duration_ms = self.started.elapsed().as_millis() as u64;
        }
    }

    pub fn spawned(&self, pid: u32) {
        self.state
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .0
            .process_id = Some(pid);
    }

    pub fn exited(&self, code: Option<i32>) {
        self.state
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .0
            .exit_code = code;
    }

    pub fn fail(&self, message: &str) {
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        if state.0.failed_at_ms.is_none() {
            state.0.failed_at_ms = Some(timestamp());
            state.0.duration_ms = self.started.elapsed().as_millis() as u64;
            state.0.failure_message = Some(message.into());
        }
    }

    /// Capture after the predecessor drains and immediately before this child starts.
    pub fn capture_log(&self, path: PathBuf) {
        let (offset, identity) = match fs::metadata(&path) {
            Ok(meta) => (Some(meta.len()), Some(FileIdentity::of(&meta))),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => (Some(0), None),
            Err(_) => (None, None),
        };
        self.state.lock().unwrap_or_else(|e| e.into_inner()).1 = Some(LogBoundary {
            path,
            offset,
            identity,
        });
    }

    pub fn report(&self) -> StartupReport {
        let (mut report, boundary) = self.state.lock().unwrap_or_else(|e| e.into_inner()).clone();
        report.os_version = system_version();
        if report.failed_at_ms.is_none() && report.phase != "ready" {
            report.duration_ms = self.started.elapsed().as_millis() as u64;
        }
        if let Some(boundary) = boundary.filter(|_| report.mode.as_deref() == Some("local")) {
            report.log_path = Some(boundary.path.display().to_string());
            if let Err(error) = read_log(&boundary, &mut report) {
                report.log_read_error = Some(error.to_string());
            }
        }
        report
    }
}

fn read_log(boundary: &LogBoundary, report: &mut StartupReport) -> std::io::Result<()> {
    let mut file = File::open(&boundary.path)?;
    let metadata = file.metadata()?;
    let length = metadata.len();
    let same_file = boundary
        .identity
        .as_ref()
        .is_none_or(|id| *id == FileIdentity::of(&metadata));
    let scoped = same_file && boundary.offset.is_some_and(|offset| offset <= length);
    let start = if scoped {
        boundary.offset.unwrap_or(0)
    } else {
        0
    };
    let offset = length.saturating_sub(LOG_LIMIT).max(start);
    report.log_excerpt_scope = Some(
        if scoped {
            "current_attempt"
        } else {
            "fallback_tail"
        }
        .into(),
    );
    report.log_excerpt_truncated = offset > start;
    file.seek(SeekFrom::Start(offset))?;
    let mut bytes = Vec::new();
    // Freeze the end as well as the start; a busy writer cannot grow this report.
    file.take(length - offset).read_to_end(&mut bytes)?;
    let text = String::from_utf8_lossy(&bytes);
    let text = if offset > start {
        text.split_once('\n')
            .map_or(text.as_ref(), |(_, rest)| rest)
    } else {
        &text
    };
    report.log_excerpt = (!text.trim().is_empty()).then(|| text.to_owned());
    Ok(())
}

fn timestamp() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn system_version() -> Option<String> {
    static VERSION: OnceLock<Option<String>> = OnceLock::new();
    VERSION
        .get_or_init(|| {
            #[cfg(target_os = "macos")]
            let output = std::process::Command::new("/usr/bin/sw_vers")
                .arg("-productVersion")
                .output();
            #[cfg(all(unix, not(target_os = "macos")))]
            let output = std::process::Command::new("uname").arg("-r").output();
            #[cfg(windows)]
            let output = {
                use std::os::windows::process::CommandExt;
                std::process::Command::new("cmd.exe")
                    .args(["/d", "/c", "ver"])
                    .creation_flags(0x08000000)
                    .output()
            };
            #[cfg(not(any(unix, windows)))]
            return None;
            #[cfg(any(unix, windows))]
            output
                .ok()
                .filter(|value| value.status.success())
                .map(|value| {
                    String::from_utf8_lossy(&value.stdout)
                        .trim()
                        .chars()
                        .take(200)
                        .collect::<String>()
                })
                .filter(|value| !value.is_empty())
        })
        .clone()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn retry_reads_only_new_bytes_and_freezes_the_first_failure() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("service.log");
        fs::write(&path, "previous failure\n").unwrap();
        let first = StartupAttempt::new(Some("local"));
        first.capture_log(path.clone());
        assert!(first.report().log_excerpt.is_none());
        fs::OpenOptions::new()
            .append(true)
            .open(&path)
            .unwrap()
            .write_all(b"current failure\n")
            .unwrap();
        first.phase("waiting_for_listener");
        first.spawned(42);
        first.exited(Some(7));
        first.fail("listener failed");
        let report = first.report();
        assert_eq!(report.log_excerpt.as_deref(), Some("current failure\n"));
        assert_eq!(report.log_excerpt_scope.as_deref(), Some("current_attempt"));
        assert_eq!(report.process_id, Some(42));
        assert_eq!(report.exit_code, Some(7));
        first.phase("ready");
        first.fail("late error");
        let frozen = first.report();
        assert_eq!(frozen.phase, "waiting_for_listener");
        assert_eq!(frozen.failure_message.as_deref(), Some("listener failed"));
        assert_eq!(frozen.failed_at_ms, report.failed_at_ms);
        assert_eq!(frozen.duration_ms, report.duration_ms);
        let retry = StartupAttempt::new(Some("local"));
        retry.capture_log(path);
        first.fail("stale completion");
        assert_ne!(retry.report().attempt_id, report.attempt_id);
        assert!(retry.report().failure_message.is_none());
        assert!(retry.report().log_excerpt.is_none());
    }

    #[test]
    fn new_files_are_scoped_and_remote_attempts_never_read_local_logs() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("service.log");
        let local = StartupAttempt::new(Some("local"));
        local.capture_log(path.clone());
        assert!(local.report().log_read_error.is_some());
        fs::write(&path, "new launch\n").unwrap();
        assert_eq!(local.report().log_excerpt.as_deref(), Some("new launch\n"));
        assert_eq!(
            local.report().log_excerpt_scope.as_deref(),
            Some("current_attempt")
        );
        let remote = StartupAttempt::new(Some("remote"));
        remote.capture_log(path);
        assert!(remote.report().log_path.is_none());
        assert!(remote.report().log_excerpt.is_none());
        assert!(remote.report().log_read_error.is_none());
    }

    #[test]
    fn truncated_and_rotated_logs_are_marked_as_bounded_fallbacks() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("service.log");
        for rotate in [false, true] {
            fs::write(&path, "old history\n".repeat(100)).unwrap();
            let attempt = StartupAttempt::new(Some("local"));
            attempt.capture_log(path.clone());
            if rotate {
                fs::rename(&path, root.path().join("rotated.log")).unwrap();
                fs::write(&path, "new line\n".repeat(LOG_LIMIT as usize)).unwrap();
            } else {
                fs::write(&path, "short\n").unwrap();
            }
            let report = attempt.report();
            assert_eq!(report.log_excerpt_scope.as_deref(), Some("fallback_tail"));
            assert_eq!(report.log_excerpt_truncated, rotate);
            assert!(report.log_excerpt.as_ref().unwrap().len() <= LOG_LIMIT as usize);
            assert!(!report.log_excerpt.unwrap().contains("old history"));
        }
    }

    #[test]
    fn large_current_attempt_is_bounded_without_previous_lines() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("service.log");
        fs::write(&path, "old\n").unwrap();
        let attempt = StartupAttempt::new(Some("local"));
        attempt.capture_log(path.clone());
        let content = "current line\n".repeat(LOG_LIMIT as usize);
        fs::OpenOptions::new()
            .append(true)
            .open(path)
            .unwrap()
            .write_all(content.as_bytes())
            .unwrap();
        let report = attempt.report();
        assert_eq!(report.log_excerpt_scope.as_deref(), Some("current_attempt"));
        assert!(report.log_excerpt_truncated);
        let excerpt = report.log_excerpt.unwrap();
        assert!(excerpt.len() <= LOG_LIMIT as usize);
        assert!(excerpt.starts_with("current line\n"));
        assert!(!excerpt.contains("old"));
    }
}
