//! Read-only launchd inspection. Process presence alone never proves deployment ownership.

use magi_service_contract::config::ServerConfig;
use serde::Serialize;
use std::path::Path;

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
// Some states are constructed only on hosts with login-service support.
#[allow(dead_code)]
pub enum Registration {
    #[default]
    NotInstalled,
    Owned,
    OtherInstallation,
    Unknown,
    Unsupported,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct ManagedService {
    pub registration: Registration,
    pub loaded: bool,
    pub pid: Option<u32>,
    pub phase: Option<String>,
    pub last_exit_code: Option<i32>,
    pub detail: Option<String>,
}

impl ManagedService {
    pub fn owned(&self) -> bool {
        self.registration == Registration::Owned
    }
}

#[cfg(target_os = "macos")]
pub fn inspect(path: &Path, config: &ServerConfig) -> ManagedService {
    match inspect_macos(path, config) {
        Ok(service) => service,
        Err(error) => ManagedService {
            registration: Registration::Unknown,
            detail: Some(error),
            ..Default::default()
        },
    }
}

#[cfg(not(target_os = "macos"))]
pub fn inspect(_path: &Path, _config: &ServerConfig) -> ManagedService {
    ManagedService {
        registration: Registration::Unsupported,
        ..Default::default()
    }
}

#[cfg(target_os = "macos")]
fn inspect_macos(path: &Path, config: &ServerConfig) -> Result<ManagedService, String> {
    use std::{fs, os::unix::fs::MetadataExt};
    let uid = unsafe { libc::geteuid() };
    let plist = crate::cli::home_path("Library/LaunchAgents/app.magi.server.plist")?;
    let target = format!("gui/{uid}/app.magi.server");
    let output = crate::launchctl::output(&["print", &target], crate::launchctl::INSPECT_TIMEOUT)?;
    // launchctl uses 113 for a missing job. Other failures are unknown, not stopped.
    if !output.status.success() && output.status.code() != Some(113) {
        return Err("Cannot inspect the login service in this user session".into());
    }
    let loaded = output.status.success();
    let metadata = match fs::symlink_metadata(&plist) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(ManagedService {
                registration: if loaded {
                    Registration::OtherInstallation
                } else {
                    Registration::NotInstalled
                },
                loaded,
                ..Default::default()
            });
        }
        Err(error) => return Err(error.to_string()),
    };
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let path = path.canonicalize().map_err(|e| e.to_string())?;
    let expected = crate::service_install::launch_agent(&executable, &path, config)?;
    if !metadata.is_file()
        || metadata.uid() != uid
        || metadata.nlink() != 1
        || metadata.len() > 65536
        || fs::read_to_string(&plist).map_err(|e| e.to_string())? != expected
    {
        return Ok(ManagedService {
            registration: Registration::OtherInstallation,
            loaded,
            ..Default::default()
        });
    }
    if !loaded {
        return Ok(ManagedService {
            registration: Registration::Owned,
            ..Default::default()
        });
    }
    parse_loaded_job(
        &String::from_utf8_lossy(&output.stdout),
        &executable,
        &path,
        config,
    )
}

#[cfg(any(test, target_os = "macos"))]
fn parse_loaded_job(
    text: &str,
    executable: &Path,
    path: &Path,
    config: &ServerConfig,
) -> Result<ManagedService, String> {
    let arguments = text
        .split_once("\n\targuments = {\n")
        .and_then(|(_, rest)| rest.split_once("\n\t}"))
        .ok_or("Cannot verify the running login service arguments")?
        .0
        .lines()
        .map(str::trim)
        .collect::<Vec<_>>();
    let log = config.data_dir.join("logs/service.log");
    let expected = [
        executable.to_str().ok_or("Invalid executable path")?,
        "run",
        "--config",
        path.to_str().ok_or("Invalid configuration path")?,
        "--log-file",
        log.to_str().ok_or("Invalid log path")?,
    ];
    if arguments != expected {
        return Ok(ManagedService {
            registration: Registration::OtherInstallation,
            loaded: true,
            ..Default::default()
        });
    }
    // Only top-level fields count; nested resource coalitions also contain a state field.
    let field = |name: &str| {
        text.lines()
            .find_map(|line| line.strip_prefix(&format!("\t{name} = ")))
    };
    let phase = field("state")
        .ok_or("Cannot inspect the running login service state")?
        .to_owned();
    let pid = field("pid")
        .map(|v| v.parse::<u32>())
        .transpose()
        .map_err(|_| "Invalid login service PID")?;
    if pid == Some(0) {
        return Err("Invalid login service PID".into());
    }
    Ok(ManagedService {
        registration: Registration::Owned,
        loaded: true,
        pid,
        phase: Some(phase),
        last_exit_code: field("last exit code").and_then(|v| v.parse().ok()),
        detail: None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn loaded_job_must_match_actual_arguments_not_only_disk_registration() {
        let root = Path::new("/Users/test/Magi data");
        let config = ServerConfig::for_bundle(Path::new("/Applications/Magi Server"), root.into());
        let text = format!("gui/501/app.magi.server = {{\n\tstate = running\n\targuments = {{\n\t\t/app/server\n\t\trun\n\t\t--config\n\t\t/config.json\n\t\t--log-file\n\t\t{}\n\t}}\n\tpid = 123\n\tlast exit code = 1\n\tresource = {{\n\t\tstate = active\n\t}}\n}}", config.data_dir.join("logs/service.log").display());
        let result = parse_loaded_job(
            &text,
            Path::new("/app/server"),
            Path::new("/config.json"),
            &config,
        )
        .unwrap();
        assert!(result.owned());
        assert_eq!(result.pid, Some(123));
        assert_eq!(result.phase.as_deref(), Some("running"));
        assert!(!parse_loaded_job(
            &text.replace("/config.json", "/other.json"),
            Path::new("/app/server"),
            Path::new("/config.json"),
            &config
        )
        .unwrap()
        .owned());
        assert!(parse_loaded_job(
            "invalid output",
            Path::new("/app/server"),
            Path::new("/config.json"),
            &config
        )
        .is_err());
    }
}
