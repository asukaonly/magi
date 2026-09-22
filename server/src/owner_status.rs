//! Read-only diagnostics tied to a currently held owner lease generation.

use magi_platform::instance::InstanceLease;
use serde::{Deserialize, Serialize};
use std::fs::{File, OpenOptions};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Starting,
    Running,
    Unresponsive,
    Backoff,
    Cooldown,
    Failed,
    Stopping,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Status {
    pub owner_pid: u32,
    pub generation: String,
    pub gateway_pid: Option<u32>,
    pub phase: Phase,
    pub restart_count: u32,
    pub last_error: Option<String>,
    pub next_retry_at_ms: Option<u64>,
    pub updated_at_ms: u64,
}

#[derive(Deserialize, Serialize, PartialEq)]
struct Identity {
    owner_pid: u32,
    generation: String,
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn open_private(path: &Path) -> Result<File, String> {
    let mut options = OpenOptions::new();
    options.read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    let file = options.open(path).map_err(|e| e.to_string())?;
    let metadata = file.metadata().map_err(|e| e.to_string())?;
    if !metadata.is_file() || metadata.len() > 16384 {
        return Err("Invalid owner diagnostics file".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.nlink() != 1 || metadata.uid() != unsafe { libc::geteuid() } {
            return Err("Owner diagnostics file has invalid ownership".into());
        }
    }
    Ok(file)
}

fn read_json<T: serde::de::DeserializeOwned>(file: &mut File) -> Result<T, String> {
    let mut bytes = Vec::new();
    file.take(16385)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() > 16384 {
        return Err("Owner diagnostics exceeds size limit".into());
    }
    serde_json::from_slice(&bytes).map_err(|e| e.to_string())
}

pub fn inspect(root: &Path) -> Option<Status> {
    let runtime = root.join("runtime");
    let mut lease = open_private(&runtime.join("owner.lock")).ok()?;
    match lease.try_lock() {
        Err(std::fs::TryLockError::WouldBlock) => {}
        Ok(()) => {
            let _ = lease.unlock();
            return None;
        }
        Err(_) => return None,
    }
    let identity: Identity = read_json(&mut lease).ok()?;
    let status: Status =
        read_json(&mut open_private(&runtime.join("owner.status.json")).ok()?).ok()?;
    if status.owner_pid == identity.owner_pid
        && status.generation == identity.generation
        && status.owner_pid > 0
        && uuid::Uuid::parse_str(&status.generation).is_ok()
    {
        Some(status)
    } else {
        None
    }
}

pub struct Publisher {
    path: PathBuf,
    status: Status,
}

impl Publisher {
    pub fn new(root: &Path, lease: &InstanceLease) -> Result<Self, String> {
        let generation = uuid::Uuid::new_v4().to_string();
        let owner_pid = std::process::id();
        // The caller's exclusive lease spans this write and every published state.
        lease.write_identity(
            &serde_json::to_vec(&Identity {
                owner_pid,
                generation: generation.clone(),
            })
            .map_err(|e| e.to_string())?,
        )?;
        let publisher = Self {
            path: root.join("runtime/owner.status.json"),
            status: Status {
                owner_pid,
                generation,
                gateway_pid: None,
                phase: Phase::Starting,
                restart_count: 0,
                last_error: None,
                next_retry_at_ms: None,
                updated_at_ms: now_ms(),
            },
        };
        publisher.save()?;
        Ok(publisher)
    }

    fn save(&self) -> Result<(), String> {
        crate::cli::replace_private_file(
            &self.path,
            &serde_json::to_vec(&self.status).map_err(|e| e.to_string())?,
        )
    }

    pub fn update(
        &mut self,
        phase: Phase,
        gateway_pid: Option<u32>,
        attempts: u32,
        error: Option<String>,
        retry: Option<Duration>,
    ) {
        self.status.phase = phase;
        self.status.gateway_pid = gateway_pid;
        self.status.restart_count = attempts;
        if error.is_some() || phase == Phase::Running {
            self.status.last_error = error;
        }
        self.status.updated_at_ms = now_ms();
        self.status.next_retry_at_ms = retry.map(|delay| {
            self.status
                .updated_at_ms
                .saturating_add(delay.as_millis() as u64)
        });
        if let Err(error) = self.save() {
            eprintln!("Could not publish owner diagnostics: {error}");
        }
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[test]
    fn stopped_or_replaced_owner_cannot_publish_a_live_status() {
        let root = std::env::temp_dir().join(format!("magi-owner-status-{}", uuid::Uuid::new_v4()));
        let lease = InstanceLease::runtime_owner(&root).unwrap();
        let mut publisher = Publisher::new(&root, &lease).unwrap();
        publisher.update(
            Phase::Cooldown,
            None,
            3,
            Some("gateway failed".into()),
            Some(Duration::from_secs(60)),
        );
        assert_eq!(inspect(&root).unwrap().phase, Phase::Cooldown);
        drop(lease);
        assert!(inspect(&root).is_none());
        let replacement = InstanceLease::runtime_owner(&root).unwrap();
        assert!(inspect(&root).is_none());
        let _new = Publisher::new(&root, &replacement).unwrap();
        assert_ne!(
            inspect(&root).unwrap().generation,
            publisher.status.generation
        );
        drop(replacement);
        std::fs::remove_dir_all(root).unwrap();
    }
}
