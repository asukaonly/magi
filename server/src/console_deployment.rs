//! Operator maintenance with explicit ownership, confirmation and stopped writes.

use crate::{
    cli,
    console::{self, ui},
    console_runtime::{self, Foreground, RunMode},
    deployment_status::{self, State},
    service_inspection::Registration,
};
use magi_platform::instance::InstanceLease;
use magi_service_contract::config::ServerConfig;
use std::{path::Path, process::Command};

fn confirm(message: &str) -> Result<bool, String> {
    ui(cliclack::confirm(message).initial_value(false).interact())
}

fn check_current_config(path: &Path, expected: &ServerConfig) -> Result<(), String> {
    let current = cli::load_config(path)?;
    if serde_json::to_value(current).map_err(|e| e.to_string())?
        != serde_json::to_value(expected).map_err(|e| e.to_string())?
    {
        return Err(
            "Deployment settings changed in another console. Reopen this action before continuing."
                .into(),
        );
    }
    Ok(())
}

fn controllable(path: &Path, config: &ServerConfig, foreground: bool) -> Result<(), String> {
    let state = deployment_status::inspect(path, config);
    if can_control(&state, foreground) {
        return Ok(());
    }
    Err("This console cannot stop the current owner. Stop the deployment in its original terminal or desktop, then return here.".into())
}

fn can_control(state: &deployment_status::Snapshot, foreground: bool) -> bool {
    foreground
        || state.managed.owned() && state.managed.loaded
        || (!state.owner_active
            && !state.management_available()
            && matches!(state.state, State::Stopped | State::PortConflict))
}

pub fn menu(path: &Path, foreground: &mut Option<Foreground>) -> Result<(), String> {
    loop {
        let config = cli::load_config(path)?;
        if foreground
            .as_ref()
            .is_some_and(|child| !child.owns(&config))
        {
            return Err("The data directory changed outside this console. Return to the original deployment before changing its service.".into());
        }
        let action = ui(cliclack::select("Deployment settings")
            .item(
                "mode",
                "Change run mode",
                "Temporary foreground or background after login",
            )
            .item(
                "port",
                "Change local port",
                "Stop this deployment, save and optionally restart",
            )
            .item(
                "paths",
                "Data, configuration and logs",
                "Show locations or open a folder",
            )
            .item(
                "upgrade",
                "Check before upgrading",
                "Read-only checks and deployment-specific instructions",
            )
            .item("back", "Back", "")
            .interact())?;
        check_current_config(path, &config)?;
        let result = match action {
            "mode" => change_mode(path, &config, foreground),
            "port" => change_port(path, &config, foreground),
            "paths" => folders(path, &config),
            "upgrade" => ui(cliclack::note("Upgrade checklist", upgrade_check(path)?)),
            _ => return Ok(()),
        };
        if let Err(error) = result {
            if error.starts_with("Setup cancelled.") {
                return Err(error);
            }
            ui(cliclack::log::warning(error))?;
        }
    }
}

fn change_mode(
    path: &Path,
    config: &ServerConfig,
    foreground: &mut Option<Foreground>,
) -> Result<(), String> {
    controllable(path, config, foreground.is_some())?;
    let current = deployment_status::inspect(path, config);
    let available = matches!(
        current.managed.registration,
        Registration::NotInstalled | Registration::Owned
    );
    let previous = if foreground.is_some() {
        Some(RunMode::Foreground)
    } else if current.managed.owned() {
        Some(RunMode::Background)
    } else {
        console_runtime::saved_mode(path)?
    };
    let mode = console::choose_run_mode("Run mode for this deployment", available, previous)?;
    let _edit = InstanceLease::acquire(&path.with_extension("edit.lock"))
        .map_err(|_| "Another deployment settings edit is active. Finish it and try again.")?;
    check_current_config(path, config)?;
    if previous == Some(mode) {
        console_runtime::save_mode(path, mode)?;
        return ui(cliclack::log::info("Run mode is unchanged."));
    }
    if !confirm(if mode == RunMode::Background {
        "Switch to background after login and start it now? Active work will be interrupted; data is preserved."
    } else {
        "Switch to temporary foreground mode? Stop this deployment and remove its login startup; data is preserved."
    })? {
        return Ok(());
    }
    check_current_config(path, config)?;
    controllable(path, config, foreground.is_some())?;
    let current = deployment_status::inspect(path, config);
    console::progress(
        "Changing run mode",
        "Previous runtime stopped",
        "Could not change run mode",
        || {
            drop(foreground.take());
            if current.managed.owned() {
                crate::service_install::execute("uninstall", path)?;
            }
            Ok(())
        },
    )?;
    if mode == RunMode::Background {
        crate::service_install::execute("install", path)?;
        console_runtime::save_mode(path, mode)?;
        crate::console_manager::wait(config, foreground)?;
        ui(cliclack::log::success(
            "Background service is ready. Closing this console leaves it running.",
        ))?;
    } else {
        console_runtime::save_mode(path, mode)?;
        ui(cliclack::log::success("Foreground mode saved. The service is stopped; choose Start this deployment to run it in this terminal."))?;
    }
    Ok(())
}

fn change_port(
    path: &Path,
    config: &ServerConfig,
    foreground: &mut Option<Foreground>,
) -> Result<(), String> {
    controllable(path, config, foreground.is_some())?;
    let original = std::fs::read(path).map_err(|e| e.to_string())?;
    check_current_config(path, config)?;
    let port: u16 = ui(cliclack::input("Local port (0 selects an available port)")
        .default_input(&config.port.to_string())
        .validate(|value: &String| {
            value
                .parse::<u16>()
                .map(|_| ())
                .map_err(|_| "Enter a port from 0 to 65535")
        })
        .interact())?;
    if port == config.port {
        return ui(cliclack::log::info("Port is unchanged."));
    }
    if port != 0 {
        let _ = std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, port))
            .map_err(|_| "That port is unavailable. Choose another port or 0.")?;
    }
    ui(cliclack::note("Port change", format!("{} -> {port}\nData stays at {}.\nUpdate any HTTPS proxy that forwards to the old local port.\nThe service will be stopped while this change is saved.", config.port, config.data_dir.display())))?;
    if !confirm("Stop this deployment and save the new port?")? {
        return Ok(());
    }
    let _edit = InstanceLease::acquire(&path.with_extension("edit.lock"))?;
    if std::fs::read(path).map_err(|e| e.to_string())? != original {
        return Err("Deployment settings changed in another console. Reopen this action to use the latest settings.".into());
    }
    check_current_config(path, config)?;
    controllable(path, config, foreground.is_some())?;
    let registered = deployment_status::inspect(path, config).managed.owned();
    console::progress(
        "Stopping this deployment",
        "Deployment stopped",
        "Could not stop deployment",
        || {
            drop(foreground.take());
            if registered {
                crate::service_install::execute("uninstall", path)?;
            }
            Ok(())
        },
    )?;
    let saved = write_port(path, &original, port);
    if let Err(error) = saved {
        if registered {
            if let Err(restore) = crate::service_install::execute("register", path) {
                return Err(format!(
                    "{error}\nLogin registration also needs repair: {restore}"
                ));
            }
        }
        return Err(error);
    }
    if registered {
        crate::service_install::execute("register", path)
            .map_err(|error| format!("Port was saved, but login registration failed: {error}. Choose background mode to register it again."))?;
        console_runtime::save_mode(path, RunMode::Background)?;
    }
    ui(cliclack::log::success(
        "Port saved. Data is unchanged; the service is stopped.",
    ))?;
    if confirm("Start this deployment with the new port now?")? {
        let config = cli::load_config(path)?;
        crate::console_manager::start(path, &config, foreground)?;
    }
    Ok(())
}

fn write_port(path: &Path, original: &[u8], port: u16) -> Result<(), String> {
    let mut config = cli::load_config(path)?;
    if std::fs::read(path).map_err(|e| e.to_string())? != original {
        return Err("Deployment configuration changed; the port was not saved.".into());
    }
    let _owner = InstanceLease::runtime_owner(&config.data_dir)?;
    let _server = InstanceLease::acquire(&config.data_dir.join("runtime/server.lock"))?;
    let _worker = InstanceLease::acquire(&config.data_dir.join("runtime/worker.lock"))?;
    config.port = port;
    config.validate()?;
    cli::replace_private_file(
        path,
        &serde_json::to_vec_pretty(&config).map_err(|e| e.to_string())?,
    )
}

fn folders(path: &Path, config: &ServerConfig) -> Result<(), String> {
    ui(cliclack::note("Deployment locations", format!(
        "Configuration: {}\nData: {}\nLogs: {}\nChanging data_dir selects another store; it does not migrate your data.",
        path.display(), config.data_dir.display(), config.data_dir.join("logs").display()
    )))?;
    let selected = ui(cliclack::select("Open a folder")
        .item("data", "Data folder", "")
        .item("config", "Configuration folder", "")
        .item("logs", "Logs folder", "")
        .item("back", "Back", "")
        .interact())?;
    let folder = match selected {
        "data" => config.data_dir.clone(),
        "config" => path
            .parent()
            .ok_or("Configuration directory is unavailable")?
            .to_path_buf(),
        "logs" => config.data_dir.join("logs"),
        _ => return Ok(()),
    };
    if !folder.is_dir() {
        return ui(cliclack::log::info(
            "This folder has not been created yet. It will appear when the service starts.",
        ));
    }
    let mut command = if cfg!(target_os = "macos") {
        Command::new("/usr/bin/open")
    } else if cfg!(windows) {
        Command::new("explorer.exe")
    } else {
        Command::new("xdg-open")
    };
    if !command
        .arg(folder)
        .status()
        .map_err(|e| e.to_string())?
        .success()
    {
        return Err(
            "The folder could not be opened. Use the displayed path in your file manager.".into(),
        );
    }
    Ok(())
}

pub fn upgrade_check(path: &Path) -> Result<String, String> {
    let config = cli::load_config(path)?;
    let state = deployment_status::inspect(path, &config);
    let runtime = match cli::validate_worker(&config) {
        Ok(()) => "Runtime files: present.".to_owned(),
        Err(error) => format!("Runtime files need attention: {error}"),
    };
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let quote = |s: &Path| format!("'{}'", s.display().to_string().replace('\'', "'\\''"));
    let stop = if state.managed.owned() {
        format!("{} uninstall --config {}", quote(&executable), quote(path))
    } else {
        "Stop the service in its original terminal or desktop.".into()
    };
    Ok(format!("{}\n{runtime}\nCurrent executable: {}\nConfiguration: {}\nData to back up: {}\n\n1. {stop}\n2. Back up the complete data directory and configuration while stopped. Verify the backup.\n3. Replace the entire service bundle at the same permanent path.\n4. Run the new executable with --config {} and start this deployment.\n5. Check status, model readiness and an existing desktop connection.\n\nThis check changes nothing. It does not verify a backup or the compatibility of a future release.",
        state.summary(false), executable.display(), path.display(), config.data_dir.display(), quote(path)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_inactive_login_registration_does_not_authorize_stopping_another_owner() {
        let mut state = deployment_status::tests::snapshot(State::Running);
        state.owner_active = true;
        state.managed.registration = Registration::Owned;
        assert!(!can_control(&state, false));
        assert!(can_control(&state, true));
        state.managed.loaded = true;
        assert!(can_control(&state, false));
        state.managed.registration = Registration::OtherInstallation;
        assert!(!can_control(&state, false));
    }

    #[cfg(unix)]
    #[test]
    fn preference_updates_do_not_follow_links_or_expose_file_contents() {
        use std::os::unix::{fs::symlink, fs::PermissionsExt};
        let root = std::env::temp_dir().join(format!("magi-preferences-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).unwrap();
        let target = root.join("original");
        std::fs::write(&target, "keep").unwrap();
        let link = root.join("link");
        symlink(&target, &link).unwrap();
        assert!(cli::replace_private_file(&link, b"replace").is_err());
        assert_eq!(std::fs::read_to_string(&target).unwrap(), "keep");
        cli::replace_private_file(&target, b"updated").unwrap();
        assert_eq!(
            std::fs::metadata(&target).unwrap().permissions().mode() & 0o777,
            0o600
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn port_edit_preserves_data_and_refuses_live_or_changed_configuration() {
        let root = std::env::temp_dir().join(format!("magi-edit-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("server.json");
        let mut config = ServerConfig::for_bundle(&root.join("bundle"), root.join("data"));
        config.worker.executable = std::env::current_exe().unwrap();
        config.worker.plugin_python = config.worker.executable.clone();
        let original = serde_json::to_vec(&config).unwrap();
        cli::create_private_file(&path, &original).unwrap();
        let owner = InstanceLease::runtime_owner(&config.data_dir).unwrap();
        assert!(write_port(&path, &original, 20000).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), original);
        drop(owner);
        std::fs::write(config.data_dir.join("keep.txt"), "business data").unwrap();
        write_port(&path, &original, 20000).unwrap();
        assert_eq!(cli::load_config(&path).unwrap().port, 20000);
        assert_eq!(
            std::fs::read_to_string(config.data_dir.join("keep.txt")).unwrap(),
            "business data"
        );
        assert!(write_port(&path, &original, 30000).is_err());
        console_runtime::save_mode(&path, RunMode::Foreground).unwrap();
        console_runtime::save_mode(&path, RunMode::Background).unwrap();
        assert!(console_runtime::saved_mode(&path).unwrap() == Some(RunMode::Background));
        std::fs::remove_dir_all(root).unwrap();
    }
}
