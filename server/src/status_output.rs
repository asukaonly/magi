//! Readable deployment reports. Process presence and service readiness are separate facts.

use crate::{
    console_api::Api,
    deployment_status::{Snapshot, State},
    service_inspection::Registration,
};
use std::path::Path;

#[derive(Debug)]
pub enum Setup {
    NotChecked,
    Incomplete,
    Complete { agent_ready: bool },
    Unavailable(String),
}

pub fn inspect_setup(snapshot: &Snapshot) -> Setup {
    if !snapshot.configuration_available() {
        return Setup::NotChecked;
    }
    let inspect = || -> Result<Setup, String> {
        let config = crate::cli::load_config(&snapshot.config_path)?;
        let api = Api::connect(&config)?;
        if !api.completed()? {
            return Ok(Setup::Incomplete);
        }
        Ok(Setup::Complete {
            agent_ready: api.agent_ready()?,
        })
    };
    inspect().unwrap_or_else(Setup::Unavailable)
}

fn identity_at_risk(snapshot: &Snapshot) -> bool {
    snapshot.data_identity_missing
        && !matches!(snapshot.state, State::Stopped | State::NotConfigured)
}

fn heading(snapshot: &Snapshot, setup: &Setup) -> &'static str {
    if identity_at_risk(snapshot) {
        return "Needs attention";
    }
    match snapshot.state {
        State::NotConfigured => "Not configured",
        State::Stopped => "Stopped",
        State::Starting => "Starting",
        State::Recovering => "Recovering",
        State::Stopping => "Stopping",
        State::Running => match setup {
            Setup::Incomplete => "Setup required",
            Setup::Complete { agent_ready: true } => "Ready",
            Setup::Complete { agent_ready: false } => "Agent not ready",
            Setup::Unavailable(_) => "Needs attention",
            Setup::NotChecked => "Configuration service ready",
        },
        State::Failed | State::Unreachable | State::PortConflict | State::Unknown => {
            "Needs attention"
        }
    }
}

fn row(lines: &mut Vec<String>, name: &str, value: impl std::fmt::Display) {
    lines.push(format!("  {name:<20} {value}"));
}

fn path_label(path: &Path) -> String {
    let status = match path.try_exists() {
        Ok(true) => "",
        Ok(false) => " [missing]",
        Err(_) => " [cannot inspect]",
    };
    format!("{}{status}", path.display())
}

fn process_label(snapshot: &Snapshot) -> String {
    if let Some(pid) = snapshot.managed.pid {
        return format!("Running (background owner PID {pid})");
    }
    if snapshot.owner_active {
        return "Active runtime lock; process not identified".into();
    }
    if snapshot.management_available() {
        return "Responding; managed by another owner".into();
    }
    if snapshot.managed.owned() && snapshot.managed.loaded {
        return "Waiting for background process".into();
    }
    if snapshot.state == State::Stopped {
        return "Stopped".into();
    }
    "Unknown".into()
}

fn management_label(snapshot: &Snapshot) -> &'static str {
    if snapshot.management_available() {
        return "Connected";
    }
    if snapshot.state == State::Stopped {
        return "Offline (service stopped)";
    }
    if snapshot
        .data_dir
        .as_ref()
        .is_some_and(|data| matches!(data.join("runtime/manage.sock").try_exists(), Ok(false)))
    {
        return "Unavailable (socket missing)";
    }
    "Unavailable (see --details)"
}

fn python_label(snapshot: &Snapshot) -> String {
    if snapshot.state == State::Stopped {
        return "Stopped".into();
    }
    let Some(management) = &snapshot.management else {
        return "Unknown (management unavailable)".into();
    };
    let phase = management
        .get("supervisor")
        .and_then(|s| s["phase"].as_str());
    match phase {
        Some("ready") => "Connected".into(),
        Some("starting") => "Starting".into(),
        Some("backoff" | "cooldown") => "Waiting to retry".into(),
        Some("unresponsive") => "Unresponsive".into(),
        Some("failed") => "Failed to start".into(),
        Some("stopping") => "Stopping".into(),
        _ => "Unknown".into(),
    }
}

fn next_steps(snapshot: &Snapshot, setup: &Setup) -> String {
    let command = |args: &[&str]| crate::operator_command::display(&snapshot.config_path, args);
    if identity_at_risk(snapshot) {
        let stop = if snapshot.managed.owned() && snapshot.managed.loaded {
            format!("1. Stop this deployment:\n     {}", command(&["stop"]))
        } else {
            "1. Stop the runtime through its original owner.".into()
        };
        return format!("{stop}\n  2. Restore its original data before restarting, or explicitly choose a fresh setup.\n     Restarting with a new identity requires devices to pair again.\n  3. After resolving the data, reopen this deployment:\n     {}\n  Do not use run or restart before resolving the missing data.", command(&[]));
    }
    match snapshot.state {
        State::NotConfigured => format!("Create this deployment:\n  {}", command(&[])),
        State::Stopped => format!("Start this deployment from the console. If data was moved, restore it first:\n  {}", command(&[])),
        State::Starting | State::Stopping => format!("Check again shortly:\n  {}\n  If this state persists, inspect logs:\n  {}", command(&["status"]), command(&["logs"])),
        State::Recovering | State::Failed => format!("Inspect the startup failure before retrying:\n  {}\n  {}", command(&["logs"]), command(&["status", "--details"])),
        State::Unreachable if snapshot.managed.owned() && snapshot.managed.loaded =>
            format!("Inspect the data paths first:\n  {}\n  If the original data is intact, restart this background deployment:\n  {}", command(&["status", "--details"]), command(&["restart"])),
        State::Unreachable | State::Unknown => format!("Inspect diagnostics and the original runtime owner before starting another instance:\n  {}", command(&["status", "--details"])),
        State::PortConflict => format!("Identify the process using the configured port. To choose another port:\n  {}", command(&["config", "edit"])),
        State::Running => match setup {
            Setup::Incomplete => format!("Finish setup:\n  {}\n  Or connect a desktop:\n  {}", command(&["configure"]), command(&["connect"])),
            Setup::Complete { agent_ready: false } => format!("Inspect Agent startup or configuration errors:\n  {}", command(&["logs", "--source", "backend"])),
            Setup::Unavailable(_) => format!("Check readiness again; inspect logs if it keeps failing:\n  {}", command(&["status", "--details"])),
            Setup::Complete { agent_ready: true } => "No action needed.".into(),
            Setup::NotChecked => format!("Check setup and Agent readiness:\n  {}", command(&["status"])),
        },
    }
}

pub fn render(snapshot: &Snapshot, setup: &Setup, details: bool) -> String {
    let title = heading(snapshot, setup);
    let tone = match title {
        "Ready" => crate::operator_output::Tone::Success,
        "Starting" | "Recovering" | "Stopping" => crate::operator_output::Tone::Pending,
        "Needs attention" | "Agent not ready" | "Setup required" => {
            crate::operator_output::Tone::Warning
        }
        _ => crate::operator_output::Tone::Info,
    };
    let mut lines = vec![tone.line(format!("Magi Server - {title}"))];
    if snapshot.state == State::Unreachable {
        lines.push(
            "A runtime is still active, but its management connection is unavailable.".into(),
        );
    } else if identity_at_risk(snapshot) {
        lines.push(
            "The service identity file is missing from the configured data directory.".into(),
        );
    }

    if snapshot.state != State::NotConfigured {
        lines.push("\nChecks".into());
        row(&mut lines, "Process", process_label(snapshot));
        row(&mut lines, "Management", management_label(snapshot));
        row(&mut lines, "Python runtime", python_label(snapshot));
        let configuration = if snapshot.configuration_available() {
            "Ready"
        } else if snapshot.management_available() {
            "Not ready"
        } else {
            "Not checked"
        };
        row(&mut lines, "Settings service", configuration);
        let agent = match setup {
            Setup::NotChecked => "Not checked",
            Setup::Incomplete => "Setup incomplete",
            Setup::Complete { agent_ready: true } => "Ready",
            Setup::Complete { agent_ready: false } => "Not ready (setup complete)",
            Setup::Unavailable(_) => "Could not check (see --details)",
        };
        row(&mut lines, "Agent", agent);
        row(
            &mut lines,
            "Service identity",
            if snapshot.data_identity_missing {
                "Missing file"
            } else {
                "File present"
            },
        );
        if let Some(url) = snapshot
            .management
            .as_ref()
            .and_then(|m| m.get("base_url"))
            .and_then(|v| v.as_str())
        {
            row(&mut lines, "Local address", url.trim_end_matches("/api"));
        }
    }

    lines.push("\nNext steps".into());
    lines.push(format!("  {}", next_steps(snapshot, setup)));
    lines.push("\nPaths".into());
    row(&mut lines, "Config", path_label(&snapshot.config_path));
    if let Some(data) = &snapshot.data_dir {
        row(&mut lines, "Data", path_label(data));
        if details || snapshot.state == State::Unreachable || identity_at_risk(snapshot) {
            row(
                &mut lines,
                "Management socket",
                path_label(&data.join("runtime/manage.sock")),
            );
            row(
                &mut lines,
                "Service identity",
                path_label(&data.join("service/server.db")),
            );
        }
    }
    if let Some(log) = &snapshot.log_path {
        row(&mut lines, "Service log", path_label(log));
    }

    if details {
        lines.push("\nTechnical details".into());
        row(
            &mut lines,
            "State",
            serde_json::to_value(snapshot.state)
                .unwrap_or_default()
                .as_str()
                .unwrap_or("unknown"),
        );
        row(
            &mut lines,
            "Login service",
            match snapshot.managed.registration {
                Registration::Owned if snapshot.managed.loaded => {
                    "Registered and loaded for this deployment"
                }
                Registration::Owned => "Registered, not loaded",
                Registration::OtherInstallation => "Belongs to another installation",
                Registration::NotInstalled => "Not installed",
                Registration::Unknown => "Could not verify ownership",
                Registration::Unsupported => "Not supported on this platform",
            },
        );
        if let Some(phase) = &snapshot.managed.phase {
            row(&mut lines, "OS process state", phase);
        }
        if let Some(code) = snapshot.managed.last_exit_code {
            row(
                &mut lines,
                "Previous exit code",
                format!("{code} (previous run; not current health)"),
            );
        }
        if let Some(m) = &snapshot.management {
            for (label, key) in [
                ("Python phase", "phase"),
                ("Python restarts", "restart_count"),
                ("Last Python error", "last_error"),
            ] {
                if let Some(value) = m
                    .get("supervisor")
                    .and_then(|s| s.get(key))
                    .filter(|v| !v.is_null())
                {
                    row(
                        &mut lines,
                        label,
                        value
                            .as_str()
                            .map(str::to_owned)
                            .unwrap_or_else(|| value.to_string()),
                    );
                }
            }
        }
        if snapshot.state != State::Stopped {
            if let Some(error) = &snapshot.management_error {
                row(&mut lines, "Management error", error);
            }
        }
        if let Some(error) = &snapshot.managed.detail {
            row(&mut lines, "Login service error", error);
        }
        if let Setup::Unavailable(error) = setup {
            row(&mut lines, "Readiness error", error);
        }
    } else {
        lines.push(
            "\nAdd --details for technical diagnostics and previous exits; --json for scripts."
                .into(),
        );
    }
    lines
        .join("\n")
        .chars()
        .filter(|c| !c.is_control() || *c == '\n')
        .take(16384)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::deployment_status::tests::snapshot;
    use serde_json::json;

    #[test]
    fn active_process_with_missing_data_never_looks_healthy() {
        let mut value = snapshot(State::Unreachable);
        let root = std::env::temp_dir().join(format!("magi-report-{}", uuid::Uuid::new_v4()));
        value.data_dir = Some(root.clone());
        value.log_path = Some(root.join("logs/service.log"));
        value.data_identity_missing = true;
        value.managed.registration = Registration::Owned;
        value.managed.loaded = true;
        value.managed.pid = Some(123);
        value.managed.phase = Some("running".into());
        value.managed.last_exit_code = Some(1);
        value.management_error = Some("No such file or directory (os error 2)".into());
        let text = render(&value, &Setup::NotChecked, false);
        assert!(text.contains("Magi Server - Needs attention"));
        assert!(text.contains("Running (background owner PID 123)"));
        assert!(text.contains("Unknown (management unavailable)"));
        assert!(text.contains("manage.sock [missing]"));
        assert!(text.contains("server.db [missing]"));
        assert!(text.contains("service.log [missing]"));
        assert!(text.contains("Restore its original data before restarting"));
        assert!(!text.contains("os error"));
        assert!(!text.contains("Previous exit code"));
        assert!(!text.contains("Use the console to restart"));
        assert!(text.contains(&crate::operator_command::display(
            &value.config_path,
            &["stop"]
        )));
        assert!(!text.contains(&crate::operator_command::display(
            &value.config_path,
            &["restart"]
        )));
        let details = render(&value, &Setup::NotChecked, true);
        assert!(details.contains("1 (previous run; not current health)"));
        assert!(details.contains("os error 2"));
        assert!(!root.exists());
        value.managed.registration = Registration::OtherInstallation;
        let text = render(&value, &Setup::NotChecked, false);
        assert!(text.contains("through its original owner"));
        assert!(!text.contains(&crate::operator_command::display(
            &value.config_path,
            &["stop"]
        )));
    }

    #[test]
    fn service_readiness_does_not_imply_agent_readiness() {
        let mut value = snapshot(State::Running);
        value.management = json!({"service_ready":true,"supervisor":{"phase":"ready"}})
            .as_object()
            .cloned();
        for (setup, title) in [
            (Setup::NotChecked, "Configuration service ready"),
            (Setup::Incomplete, "Setup required"),
            (Setup::Complete { agent_ready: false }, "Agent not ready"),
            (Setup::Complete { agent_ready: true }, "Ready"),
            (
                Setup::Unavailable("Request timed out".into()),
                "Needs attention",
            ),
        ] {
            let text = render(&value, &setup, false);
            assert!(text.contains(&format!("Magi Server - {title}\n")));
            assert!(!text.contains("Request timed out"));
        }
        value.data_identity_missing = true;
        assert!(
            render(&value, &Setup::Complete { agent_ready: true }, false)
                .contains("Magi Server - Needs attention")
        );
    }

    #[test]
    fn stopped_and_unconfigured_deployments_are_normal_empty_states() {
        for (state, title) in [
            (State::NotConfigured, "Not configured"),
            (State::Stopped, "Stopped"),
        ] {
            let mut value = snapshot(state);
            value.data_identity_missing = true;
            value.management_error = Some("No such file or directory".into());
            let text = render(&value, &Setup::NotChecked, false);
            assert!(text.contains(&format!("Magi Server - {title}\n")));
            assert!(!text.contains("Needs attention"));
            assert!(!text.contains("socket missing"));
            assert!(!text.contains("No such file"));
            assert!(!text.contains("pair again"));
        }
    }

    #[test]
    fn recovering_runtime_and_other_installation_have_distinct_guidance() {
        let mut value = snapshot(State::Recovering);
        value.management = json!({"service_ready":false,"supervisor":{"phase":"cooldown","restart_count":2,"last_error":"probe timed out"}}).as_object().cloned();
        let text = render(&value, &Setup::NotChecked, false);
        assert!(text.contains("Magi Server - Recovering"));
        assert!(text.contains("Waiting to retry"));
        assert!(render(&value, &Setup::NotChecked, true).contains("probe timed out"));
        value = snapshot(State::PortConflict);
        value.managed.registration = Registration::OtherInstallation;
        value.managed.loaded = true;
        assert!(
            render(&value, &Setup::NotChecked, true).contains("Belongs to another installation")
        );
        assert!(!render(&value, &Setup::NotChecked, false).contains("restart the verified"));
    }
}
