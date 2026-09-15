//! State-driven console navigation; the menu never implicitly adopts a live service.

use crate::{
    console::{self, ui},
    console_api::{management, Api, Request},
    console_runtime::{self, Foreground, RunMode},
    deployment_status::{self, Snapshot, State},
    service_inspection::Registration,
};
use magi_service_contract::config::ServerConfig;
use std::path::Path;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    Start,
    Configure,
    Pair,
    Devices,
    Status,
    Logs,
    Check,
    Wait,
    Service,
    KeepRunning,
    Exit,
}

fn actions(snapshot: &Snapshot, foreground: bool) -> Vec<Action> {
    let mut result = if snapshot.configuration_available() {
        vec![
            Action::Configure,
            Action::Pair,
            Action::Devices,
            Action::Status,
            Action::Logs,
        ]
    } else if snapshot.can_start() {
        vec![Action::Start, Action::Status, Action::Logs]
    } else {
        vec![Action::Status, Action::Check, Action::Logs]
    };
    if matches!(snapshot.state, State::Starting | State::Recovering) {
        result.push(Action::Wait);
    }
    if !snapshot.configuration_available() && snapshot.management_available() {
        result.extend([Action::Pair, Action::Devices]);
    }
    if snapshot.managed.owned() && !foreground {
        result.push(Action::Service);
    }
    if foreground {
        result.push(Action::KeepRunning);
    }
    result.push(Action::Exit);
    result
}

pub fn run(path: &Path, config: &ServerConfig) -> Result<(), String> {
    let mut foreground: Option<Foreground> = None;
    loop {
        if let Some(child) = &mut foreground {
            if let Err(error) = child.check_running() {
                ui(cliclack::log::warning(error))?;
                foreground.take();
            }
        }
        let snapshot = deployment_status::inspect(path, config);
        ui(cliclack::note("Service state", snapshot.describe()))?;
        let completed = if snapshot.configuration_available() {
            match console::progress(
                "Checking Magi configuration and Agent readiness",
                "Configuration status checked",
                "Configuration status is unavailable",
                || {
                    let api = Api::connect(config)?;
                    let completed = api.completed()?;
                    Ok((completed, completed.then(|| api.agent_ready())))
                },
            ) {
                Ok((completed, agent)) => {
                    ui(cliclack::log::info(if completed {
                        "Setup is complete. Changes here apply to every device connected to this Magi."
                    } else {
                        "Setup is incomplete. Continue with the saved configuration, or connect a desktop to finish."
                    }))?;
                    match agent {
                        Some(Ok(true)) => ui(cliclack::log::info("Agent is ready."))?,
                        Some(Ok(false)) => ui(cliclack::log::warning("Setup is saved, but the Agent is not ready yet. Check diagnostics and logs."))?,
                        Some(Err(error)) => ui(cliclack::log::warning(format!("Agent readiness could not be checked: {}", console::clean(&error))))?,
                        None => {},
                    }
                    Some(completed)
                }
                Err(error) => {
                    ui(cliclack::log::warning(console::clean(&error)))?;
                    None
                }
            }
        } else {
            None
        };
        let exit_hint = if foreground.is_some() {
            "This console owns the foreground service. Closing it stops that service."
        } else {
            "Exiting this console leaves existing and background services running."
        };
        ui(cliclack::log::info(exit_hint))?;
        let mut menu = cliclack::select("What would you like to do?");
        for action in actions(&snapshot, foreground.is_some()) {
            let (title, hint) = match action {
                Action::Start => (
                    "Start this deployment",
                    "Uses the saved run mode, or asks on first use",
                ),
                Action::Configure if completed != Some(false) => {
                    ("Configure Magi", "Models, language and default persona")
                }
                Action::Configure => (
                    "Continue setup",
                    "Keep saved steps; configure here or finish in desktop",
                ),
                Action::Pair => (
                    "Connect another device",
                    "Generate a single-use pairing code valid for 30 minutes",
                ),
                Action::Devices => (
                    "Manage paired devices",
                    "Inspect administrator and collector devices; revoke access",
                ),
                Action::Status => (
                    "View diagnostics",
                    "Deployment, process state and configuration paths",
                ),
                Action::Logs => ("View recent service logs", "Show the latest 40 lines"),
                Action::Check => ("Check again", "Refresh the service state"),
                Action::Wait => (
                    "Wait for the configuration service",
                    "Show elapsed time and runtime progress; bounded by startup timeout",
                ),
                Action::Service => (
                    "Background service options",
                    "Start, restart, stop or uninstall this verified deployment",
                ),
                Action::KeepRunning => (
                    "Keep running in this terminal",
                    "Leave the menu; Ctrl+C stops this foreground service",
                ),
                Action::Exit if foreground.is_some() => (
                    "Stop this foreground service and exit",
                    "Only the service started by this console",
                ),
                Action::Exit => ("Exit console", "Keep existing services running"),
            };
            menu = menu.item(action, title, hint);
        }
        let action = ui(menu.interact())?;
        let result = match action {
            Action::Exit => {
                if foreground.is_some()
                    && !confirm("Stop the foreground service started by this console and exit?")?
                {
                    continue;
                }
                let owned_foreground = foreground.is_some();
                drop(foreground.take());
                ui(cliclack::outro(if snapshot.can_start() {
                    "Console closed. Deployment remains stopped."
                } else if snapshot.state == State::Running && !owned_foreground {
                    "Console closed. The existing service remains running."
                } else {
                    "Console closed. Saved configuration is retained."
                }))?;
                return Ok(());
            }
            Action::KeepRunning => {
                ui(cliclack::outro(
                    "Running in foreground. Press Ctrl+C to stop this service.",
                ))?;
                return foreground
                    .take()
                    .ok_or("Foreground service is no longer owned by this console")?
                    .wait();
            }
            Action::Check => Ok(()),
            Action::Status => {
                ui(cliclack::note(
                    "Deployment diagnostics",
                    snapshot.describe(),
                ))?;
                Ok(())
            }
            Action::Logs => deployment_status::log_tail(config, 40).and_then(|text| {
                ui(cliclack::note(
                    "Recent service logs",
                    if text.is_empty() {
                        "No service log entries yet."
                    } else {
                        &text
                    },
                ))
            }),
            Action::Wait => wait(config, &mut foreground),
            Action::Start => {
                start(path, config, &mut foreground).and_then(|_| setup_if_needed(config))
            }
            Action::Configure => Api::connect(config).and_then(|api| {
                if api.completed()? {
                    console::edit_configuration(&api)
                } else {
                    setup_if_needed(config)
                }
            }),
            Action::Pair => Api::connect(config).and_then(|api| console::pairing(config, &api)),
            Action::Devices => devices(config),
            Action::Service => service_options(path, config, &mut foreground),
        };
        if let Err(error) = result {
            if error.starts_with("Setup cancelled.") {
                return Err(error);
            }
            ui(cliclack::log::warning(
                error
                    .chars()
                    .filter(|c| !c.is_control() || *c == '\n')
                    .take(8192)
                    .collect::<String>(),
            ))?;
        }
    }
}

fn confirm(prompt: &str) -> Result<bool, String> {
    ui(cliclack::confirm(prompt).initial_value(false).interact())
}

fn wait(config: &ServerConfig, foreground: &mut Option<Foreground>) -> Result<(), String> {
    let spinner = cliclack::spinner();
    spinner.start("Waiting for the configuration service");
    let result =
        console_runtime::wait_ready(config, foreground, |detail| spinner.set_message(detail));
    if result.is_ok() {
        spinner.stop("Configuration service is ready");
    } else {
        spinner.error("Configuration service is unavailable; returning to recovery options");
    }
    drop(spinner);
    result
}

fn start(
    path: &Path,
    config: &ServerConfig,
    foreground: &mut Option<Foreground>,
) -> Result<(), String> {
    let current = deployment_status::inspect(path, config);
    if !current.can_start() {
        return Err(current.recovery_hint());
    }
    crate::cli::validate_worker(config)?;
    let mode = match console_runtime::saved_mode(path)? {
        Some(RunMode::Background)
            if matches!(
                current.managed.registration,
                Registration::OtherInstallation | Registration::Unsupported
            ) =>
        {
            return Err("The saved background mode is unavailable for this installation. Inspect the registered service or use an explicit foreground run.".into());
        }
        Some(mode) => mode,
        None => {
            let mode = console::run_mode(matches!(
                current.managed.registration,
                Registration::NotInstalled | Registration::Owned
            ))?;
            console_runtime::save_mode(path, mode)?;
            mode
        }
    };
    match mode {
        RunMode::Background => {
            console::progress(
                "Requesting background startup",
                "Background start requested",
                "Background start failed",
                || crate::service_install::execute("install", path),
            )?;
        }
        RunMode::Foreground => *foreground = Some(Foreground::start(path, config)?),
    }
    wait(config, foreground)
}

fn setup_if_needed(config: &ServerConfig) -> Result<(), String> {
    let api = Api::connect(config)?;
    if api.completed()? {
        return Ok(());
    }
    let terminal = ui(cliclack::select("2/5 · Setup method")
        .item(
            true,
            "Configure in this terminal",
            "Continue saved language, model and persona settings",
        )
        .item(
            false,
            "Continue in desktop",
            "Generate a pairing code and finish in Magi desktop",
        )
        .interact())?;
    if terminal {
        console::interactive_configure(&api)?;
    }
    console::pairing(config, &api)
}

fn devices(config: &ServerConfig) -> Result<(), String> {
    let value = management(config, Request::Clients)?;
    let entries = value.as_array().ok_or("Invalid paired-device response")?;
    let mut select = cliclack::select("Paired devices — select one to revoke access");
    for entry in entries.iter().filter(|v| v["revoked_at_ms"].is_null()) {
        let id = crate::console_api::string(entry, "client_id")?;
        let name = crate::console_api::string(entry, "name")?;
        let role = entry["role"].as_str().unwrap_or("unknown");
        select = select.item(
            Some(id.to_owned()),
            console::clean(name),
            format!("{role} · {id}"),
        );
    }
    select = select.item(None, "Back", "Keep device access unchanged");
    if let Some(id) = ui(select.interact())? {
        if confirm("Revoke this device's access? It will need a new pairing code to reconnect.")? {
            management(config, Request::Revoke { client_id: id })?;
            ui(cliclack::log::success("Device access revoked"))?;
        }
    }
    Ok(())
}

fn service_options(
    path: &Path,
    config: &ServerConfig,
    foreground: &mut Option<Foreground>,
) -> Result<(), String> {
    let current = deployment_status::inspect(path, config);
    if !current.managed.owned() {
        return Err("The registered service no longer belongs to this deployment".into());
    }
    let mut select = cliclack::select("Background service");
    if current.can_start() {
        select = select.item(
            "start",
            "Start background service",
            "Uses this registered deployment",
        );
    }
    if current.managed.loaded {
        select = select
            .item(
                "restart",
                "Restart background service",
                "Interrupt active work and reconnect devices",
            )
            .item(
                "stop",
                "Stop background service",
                "Disconnect devices; keep data and configuration",
            );
    }
    select = select
        .item(
            "uninstall",
            "Uninstall background service",
            "Stop it and remove login startup; keep all data",
        )
        .item("back", "Back", "");
    let action = ui(select.interact())?;
    if action == "back" {
        return Ok(());
    }
    if !confirm(&format!(
        "{} this background service?",
        match action {
            "start" => "Start",
            "restart" => "Restart",
            "stop" => "Stop",
            _ => "Uninstall",
        }
    ))? {
        return Ok(());
    }
    if matches!(action, "start" | "restart") && current.data_identity_missing
        && !confirm("The current data directory has no server identity. Continue using this directory? Moved data will not be restored automatically.")? { return Ok(()); }
    if foreground.is_some() {
        return Err(
            "Stop this console's foreground service before changing the background registration"
                .into(),
        );
    }
    console::progress(
        "Applying background service action",
        "Background service action completed",
        "Background service action failed",
        || crate::service_install::execute(action, path),
    )?;
    if matches!(action, "start" | "restart") {
        wait(config, foreground)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::deployment_status::tests::snapshot;
    use serde_json::json;

    #[test]
    fn healthy_service_offers_management_without_start_or_restart() {
        let mut value = snapshot(State::Running);
        value.management = json!({"service_ready":true}).as_object().cloned();
        let menu = actions(&value, false);
        assert!(menu.contains(&Action::Configure));
        assert!(menu.contains(&Action::Pair));
        assert!(menu.contains(&Action::Devices));
        assert!(!menu.contains(&Action::Start));
        assert!(!menu.contains(&Action::Wait));
        assert!(!menu.contains(&Action::KeepRunning));
    }

    #[test]
    fn incomplete_runtime_retains_native_pairing_but_blocks_python_configuration() {
        let mut value = snapshot(State::Recovering);
        value.management = json!({"service_ready":false}).as_object().cloned();
        let menu = actions(&value, false);
        assert!(menu.contains(&Action::Pair));
        assert!(menu.contains(&Action::Devices));
        assert!(menu.contains(&Action::Wait));
        assert!(!menu.contains(&Action::Configure));
        assert!(!menu.contains(&Action::Start));
    }

    #[test]
    fn unreachable_service_never_defaults_to_blind_wait_or_duplicate_start() {
        let mut value = snapshot(State::Unreachable);
        value.managed.registration = Registration::Owned;
        value.managed.loaded = true;
        let menu = actions(&value, false);
        assert_eq!(menu.first(), Some(&Action::Status));
        assert!(menu.contains(&Action::Service));
        assert!(!menu.contains(&Action::Wait));
        assert!(!menu.contains(&Action::Start));
        value.managed.registration = Registration::OtherInstallation;
        assert!(!actions(&value, false).contains(&Action::Service));
    }

    #[test]
    fn stopped_deployment_can_start_and_foreground_ownership_stays_explicit() {
        assert_eq!(
            actions(&snapshot(State::Stopped), false).first(),
            Some(&Action::Start)
        );
        let mut value = snapshot(State::Running);
        value.managed.registration = Registration::Owned;
        let menu = actions(&value, true);
        assert!(menu.contains(&Action::KeepRunning));
        assert!(!menu.contains(&Action::Service));
        for state in [
            State::Failed,
            State::Stopping,
            State::Unknown,
            State::PortConflict,
        ] {
            let menu = actions(&snapshot(state), false);
            assert!(!menu.contains(&Action::Start));
            assert!(!menu.contains(&Action::Wait));
        }
    }
}
