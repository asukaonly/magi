//! One read-only deployment snapshot shared by interactive and explicit commands.

use crate::{
    console_api::{management, Request},
    service_inspection::{self, ManagedService, Registration},
};
use magi_platform::instance::InstanceLease;
use magi_service_contract::config::ServerConfig;
use serde::Serialize;
use serde_json::{Map, Value};
use std::{
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    time::Duration,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    NotConfigured,
    Stopped,
    Running,
    Starting,
    Recovering,
    Failed,
    Stopping,
    Unreachable,
    PortConflict,
    Unknown,
}

#[derive(Clone, Debug, Serialize)]
pub struct Snapshot {
    pub state: State,
    pub message: String,
    pub config_path: PathBuf,
    pub data_dir: Option<PathBuf>,
    pub log_path: Option<PathBuf>,
    pub managed: ManagedService,
    pub owner_active: bool,
    pub data_identity_missing: bool,
    pub management_error: Option<String>,
    #[serde(flatten)]
    pub management: Option<Map<String, Value>>,
}

impl Snapshot {
    pub fn summary(&self, foreground: bool) -> String {
        let state = if foreground && self.state == State::Running {
            "Magi is running in this terminal."
        } else {
            &self.message
        };
        let address = self
            .management
            .as_ref()
            .and_then(|m| m.get("base_url"))
            .and_then(Value::as_str)
            .map(|url| format!("\nLocal address: {}", url.trim_end_matches("/api")))
            .unwrap_or_default();
        format!("{state}{address}")
    }
    pub fn configuration_available(&self) -> bool {
        self.state == State::Running
    }
    pub fn management_available(&self) -> bool {
        self.management.is_some()
    }
    pub fn can_start(&self) -> bool {
        self.state == State::Stopped
    }
    pub fn recovery_hint(&self) -> String {
        let command = self
            .config_path
            .display()
            .to_string()
            .replace('\'', "'\\''");
        let next = if self.managed.owned() && self.managed.loaded {
            format!("Check logs or run magi-server restart --config '{command}'.")
        } else if self.can_start() {
            format!("Run magi-server --config '{command}' to start this deployment.")
        } else {
            "Check status and the original owner. Do not start another service against this data directory.".into()
        };
        format!("{} {next}", self.message)
    }
    pub fn describe(&self) -> String {
        crate::status_output::render(self, &crate::status_output::Setup::NotChecked, true)
    }
}

pub fn inspect_path(path: &Path) -> Result<Snapshot, String> {
    if !path.try_exists().map_err(|e| e.to_string())? {
        return Ok(Snapshot { state: State::NotConfigured, message: "No deployment configuration exists. Run magi-server for guided setup, or init for automation.".into(),
            config_path: path.into(), data_dir: None, log_path: None, managed: ManagedService::default(), owner_active: false,
            data_identity_missing: true, management_error: None, management: None });
    }
    let config = crate::cli::load_config(path)?;
    Ok(inspect(path, &config))
}

pub fn inspect(path: &Path, config: &ServerConfig) -> Snapshot {
    let managed = service_inspection::inspect(path, config);
    let result = management(config, Request::Status).and_then(|v| {
        let m = v.as_object().ok_or("Invalid management status")?;
        if m.get("protocol_version").and_then(Value::as_u64) != Some(u64::from(magi_service_contract::SERVER_PROTOCOL_VERSION))
            || m.get("service_ready").and_then(Value::as_bool).is_none() {
            return Err("The running service does not match this CLI protocol. Use its matching installation or restart the verified deployment.".into());
        }
        Ok(m.clone())
    });
    let mut snapshot = Snapshot {
        state: State::Unknown,
        message: String::new(),
        config_path: path.into(),
        data_dir: Some(config.data_dir.clone()),
        log_path: Some(config.data_dir.join("logs/service.log")),
        managed,
        owner_active: false,
        data_identity_missing: !config.data_dir.join("service/server.db").is_file(),
        management_error: result.as_ref().err().cloned(),
        management: result.ok(),
    };
    let mut lease_error = None;
    for file in ["owner.lock", "server.lock", "worker.lock"] {
        match InstanceLease::is_held(&config.data_dir.join("runtime").join(file)) {
            Ok(held) => snapshot.owner_active |= held,
            Err(error) => lease_error = Some(error),
        }
    }
    let occupied = snapshot.management.is_none()
        && config.port != 0
        && TcpStream::connect_timeout(
            &SocketAddr::from(([127, 0, 0, 1], config.port)),
            Duration::from_millis(200),
        )
        .is_ok();
    snapshot.state = classify(&snapshot, lease_error.is_some(), occupied);
    snapshot.message = match snapshot.state {
        State::Running => if snapshot.managed.owned() && snapshot.managed.pid.is_some() { "Magi is running in the background." } else { "Magi is running under an existing owner." },
        State::Starting => "The configuration service is starting.",
        State::Recovering if snapshot.management.is_none() => "The background job is loaded but has no running process. Check recent exits and service logs.",
        State::Recovering => "The service is recovering. Model setup is not the cause of this wait.",
        State::Failed => "The runtime could not start. Inspect its last error before retrying.",
        State::Stopping => "The service is stopping. Wait for it to finish before starting again.",
        State::Unreachable => "An existing runtime is active, but its management connection is unavailable. Check whether its runtime directory was moved.",
        State::PortConflict => "The configured port is occupied, but this deployment cannot be reached. The port alone does not identify its owner.",
        State::Stopped => "Saved deployment found. The service is stopped.",
        State::Unknown => "The service state could not be verified. Inspect diagnostics before starting another instance.",
        State::NotConfigured => unreachable!(),
    }.into();
    if let Some(error) = lease_error {
        snapshot.management_error.get_or_insert(error);
    }
    snapshot
}

fn classify(snapshot: &Snapshot, lease_error: bool, occupied: bool) -> State {
    if let Some(m) = &snapshot.management {
        return match m
            .get("supervisor")
            .and_then(|s| s.get("phase"))
            .and_then(Value::as_str)
        {
            Some("backoff" | "cooldown" | "unresponsive") => State::Recovering,
            Some("failed") => State::Failed,
            Some("stopping") => State::Stopping,
            _ if m.get("service_ready") == Some(&Value::Bool(true)) => State::Running,
            _ => State::Starting,
        };
    }
    if snapshot.owner_active {
        return State::Unreachable;
    }
    if snapshot.managed.owned() && snapshot.managed.loaded {
        return if snapshot.managed.pid.is_some() {
            State::Unreachable
        } else {
            State::Recovering
        };
    }
    if lease_error || snapshot.managed.registration == Registration::Unknown {
        return State::Unknown;
    }
    if occupied {
        return State::PortConflict;
    }
    State::Stopped
}

pub fn require_management(
    config: &ServerConfig,
    path: &Path,
    ready: bool,
) -> Result<Snapshot, String> {
    let snapshot = inspect(path, config);
    if snapshot.management_available() && (!ready || snapshot.configuration_available()) {
        Ok(snapshot)
    } else {
        Err(snapshot.recovery_hint())
    }
}

pub fn log_tail(config: &ServerConfig, lines: usize) -> Result<String, String> {
    crate::operator_logs::tail(&config.data_dir.join("logs/service.log"), lines)
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn normal_stopped_summary_does_not_report_a_missing_socket_as_failure() {
        let mut value = snapshot(State::Stopped);
        value.message = "The service is stopped.".into();
        value.management_error = Some("No such file or directory".into());
        assert!(!value.summary(false).contains("No such file"));
        assert!(!value.describe().contains("No such file"));
        value.state = State::Unreachable;
        assert!(value.describe().contains("No such file"));
    }

    pub fn snapshot(state: State) -> Snapshot {
        Snapshot {
            state,
            message: String::new(),
            config_path: "/test/config.json".into(),
            data_dir: None,
            log_path: None,
            managed: ManagedService::default(),
            owner_active: false,
            data_identity_missing: false,
            management_error: None,
            management: None,
        }
    }

    #[test]
    fn runtime_phase_and_configuration_readiness_are_distinct() {
        for (ready, phase, expected) in [
            (true, "ready", State::Running),
            (false, "starting", State::Starting),
            (false, "ready", State::Starting),
            (false, "backoff", State::Recovering),
            (false, "cooldown", State::Recovering),
            (false, "unresponsive", State::Recovering),
            (false, "failed", State::Failed),
            (false, "stopping", State::Stopping),
            (true, "stopping", State::Stopping),
        ] {
            let mut value = snapshot(State::Unknown);
            value.management = json!({"service_ready":ready,"supervisor":{"phase":phase}})
                .as_object()
                .cloned();
            assert_eq!(classify(&value, false, false), expected, "{ready} {phase}");
        }
    }

    #[test]
    fn missing_endpoint_does_not_mean_stopped_or_authorize_a_port_owner() {
        let mut value = snapshot(State::Unknown);
        assert_eq!(classify(&value, false, false), State::Stopped);
        assert_eq!(classify(&value, false, true), State::PortConflict);
        assert_eq!(classify(&value, true, false), State::Unknown);
        value.owner_active = true;
        assert_eq!(classify(&value, false, false), State::Unreachable);
        value.owner_active = false;
        value.managed.registration = Registration::Owned;
        value.managed.loaded = true;
        value.managed.pid = Some(123);
        // A moved runtime directory can hide all leases and sockets from the CLI.
        assert_eq!(classify(&value, false, false), State::Unreachable);
        value.managed.pid = None;
        assert_eq!(classify(&value, false, false), State::Recovering);
        value.managed.loaded = false;
        assert_eq!(classify(&value, false, false), State::Stopped);
        value.managed.registration = Registration::Unknown;
        assert_eq!(classify(&value, false, false), State::Unknown);
        value.managed.registration = Registration::OtherInstallation;
        value.managed.loaded = true;
        assert_eq!(classify(&value, false, true), State::PortConflict);
        assert!(!value.managed.owned());
    }

    #[test]
    fn unconfigured_status_does_not_create_any_files() {
        let root = std::env::temp_dir().join(format!("magi-status-{}", uuid::Uuid::new_v4()));
        let status = inspect_path(&root.join("config.json")).unwrap();
        assert_eq!(status.state, State::NotConfigured);
        assert!(!status.can_start());
        assert!(!root.exists());
    }
}
