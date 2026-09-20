//! User-session service installation. Business data is never removed here.

#[cfg(target_os = "macos")]
use magi_service_contract::config::ServerConfig;
use std::path::Path;

#[cfg(target_os = "macos")]
const LABEL: &str = "app.magi.server";

#[cfg(target_os = "macos")]
fn xml(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

#[cfg(target_os = "macos")]
pub(crate) fn launch_agent(
    executable: &Path,
    config_path: &Path,
    config: &ServerConfig,
) -> Result<String, String> {
    let text = |path: &Path| {
        path.to_str()
            .map(xml)
            .ok_or_else(|| "Service paths must be valid UTF-8".to_owned())
    };
    Ok(format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{LABEL}</string>
<key>ProgramArguments</key><array><string>{}</string><string>run</string><string>--config</string><string>{}</string><string>--log-file</string><string>{}</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>30</integer>
<key>ExitTimeOut</key><integer>{}</integer>
<key>ProcessType</key><string>Background</string>
<key>LimitLoadToSessionType</key><string>Aqua</string>
<key>Umask</key><integer>63</integer>
</dict></plist>
"#,
        text(executable)?,
        text(config_path)?,
        text(&config.data_dir.join("logs/service.log"))?,
        config.owner_shutdown_timeout_secs()
    ))
}

#[cfg(target_os = "macos")]
pub fn execute(command: &str, config_path: &Path) -> Result<serde_json::Value, String> {
    execute_with_progress(command, config_path, &|_| {})
}

pub fn execute_cli(command: &str, config_path: &Path) -> Result<serde_json::Value, String> {
    crate::operator_progress::run(|progress| execute_with_progress(command, config_path, progress))
        .map_err(|error| {
            format!(
                "{error}\nCheck this deployment:\n  {}",
                crate::operator_command::display(config_path, &["status"])
            )
        })
}

#[cfg(target_os = "macos")]
fn execute_with_progress(
    command: &str,
    config_path: &Path,
    progress: &dyn Fn(&str),
) -> Result<serde_json::Value, String> {
    use std::{
        fs,
        io::Write,
        os::unix::fs::{MetadataExt, OpenOptionsExt},
        time::{Duration, Instant},
    };
    progress("Checking background service ownership...");
    let config = crate::cli::load_config(config_path)?;
    let config_path = config_path.canonicalize().map_err(|e| e.to_string())?;
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let expected = launch_agent(&executable, &config_path, &config)?;
    let inspected = crate::service_inspection::inspect(&config_path, &config);
    use crate::service_inspection::Registration;
    if matches!(
        inspected.registration,
        Registration::OtherInstallation | Registration::Unknown
    ) {
        return Err(format!("Cannot manage this login service: its deployment ownership could not be verified. {} Inspect status and use the matching executable and configuration.", inspected.detail.as_deref().unwrap_or("The registration belongs to another installation.")));
    }
    // A user agent must run under the logged-in owner, never as a root daemon.
    let uid = unsafe { libc::geteuid() };
    if uid == 0 {
        return Err("Install the service as the logged-in user, without sudo".into());
    }
    let home = std::env::var_os("HOME").ok_or("User home is unavailable")?;
    let directory = Path::new(&home).join("Library/LaunchAgents");
    let plist = directory.join(format!("{LABEL}.plist"));
    let domain = format!("gui/{uid}");
    let target = format!("{domain}/{LABEL}");
    let launchctl = |args: &[&str], timeout: Duration| -> Result<(), String> {
        let output = crate::launchctl::output(args, timeout)?;
        if output.status.success() {
            Ok(())
        } else {
            Err(format!(
                "launchctl failed: {}",
                String::from_utf8_lossy(&output.stderr).trim()
            ))
        }
    };
    let loaded = |timeout: Duration| -> Result<bool, String> {
        let output = crate::launchctl::output(&["print", &target], timeout)?;
        loaded_from_status(output.status.success(), output.status.code())
    };
    let unload = || -> Result<(), String> {
        let deadline =
            Instant::now() + Duration::from_secs(config.owner_shutdown_timeout_secs() + 10);
        let remaining = || {
            deadline.checked_duration_since(Instant::now()).filter(|d| !d.is_zero())
                .ok_or_else(|| "Timed out waiting for the managed service to unload. Check status before retrying.".to_string())
        };
        if loaded(remaining()?.min(crate::launchctl::INSPECT_TIMEOUT))? {
            progress(&format!(
                "Stopping background service (shutdown budget: {}s; stop deadline: {}s)...",
                config.owner_shutdown_timeout_secs(),
                config.owner_shutdown_timeout_secs() + 10
            ));
            launchctl(&["bootout", &target], remaining()?)?;
        } else {
            progress("Background service is already stopped.");
            return Ok(());
        }
        // The deadline includes bootout itself, not only the later removal check.
        progress("Confirming that macOS has removed the background job...");
        while loaded(remaining()?.min(crate::launchctl::INSPECT_TIMEOUT))? {
            std::thread::sleep(Duration::from_millis(100).min(remaining()?));
        }
        progress("Background service stopped. Data is preserved.");
        Ok(())
    };
    if matches!(command, "install" | "register") {
        fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
        if !plist.exists() {
            // Pre-create the service-owned log directory before launchd starts it.
            magi_platform::private_data::protect_magi_data_root(&config.data_dir)?;
            fs::create_dir_all(config.data_dir.join("logs")).map_err(|e| e.to_string())?;
            magi_platform::private_data::protect_magi_data_root(&config.data_dir)?;
            let mut file = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .custom_flags(libc::O_NOFOLLOW)
                .open(&plist)
                .map_err(|e| e.to_string())?;
            file.write_all(expected.as_bytes())
                .and_then(|_| file.sync_all())
                .map_err(|e| e.to_string())?;
        }
    }
    let metadata =
        fs::symlink_metadata(&plist).map_err(|_| "Service is not installed; run install first")?;
    if !metadata.is_file()
        || metadata.uid() != uid
        || metadata.nlink() != 1
        || fs::read_to_string(&plist).map_err(|e| e.to_string())? != expected
    {
        return Err("The existing launch agent belongs to a different installation; use its original executable and configuration to uninstall it first".into());
    }
    let plist_arg = plist.to_str().ok_or("Launch agent path is not UTF-8")?;
    match command {
        "register" => {}
        "install" | "start" => {
            progress("Requesting background startup from macOS...");
            if !loaded(crate::launchctl::INSPECT_TIMEOUT)? {
                launchctl(&["enable", &target], crate::launchctl::CONTROL_TIMEOUT)?;
                launchctl(
                    &["bootstrap", &domain, plist_arg],
                    crate::launchctl::CONTROL_TIMEOUT,
                )?;
            }
            launchctl(&["kickstart", &target], crate::launchctl::CONTROL_TIMEOUT)?;
        }
        "stop" | "uninstall" => {
            unload()?;
            if command == "uninstall" {
                fs::remove_file(&plist).map_err(|e| e.to_string())?;
            }
        }
        "restart" => {
            unload()?;
            progress("Requesting background startup from macOS...");
            launchctl(&["enable", &target], crate::launchctl::CONTROL_TIMEOUT)?;
            launchctl(
                &["bootstrap", &domain, plist_arg],
                crate::launchctl::CONTROL_TIMEOUT,
            )?;
            launchctl(&["kickstart", &target], crate::launchctl::CONTROL_TIMEOUT)?;
        }
        _ => return Err("Unknown service installation command".into()),
    }
    // The caller owns presentation: JSON for automation, step feedback for the wizard.
    Ok(
        serde_json::json!({"command":command,"launch_agent":plist,"data_dir":config.data_dir,"data_preserved":true,
            "outcome": if command == "register" { "registered" } else if matches!(command, "install" | "start") && inspected.loaded { "already_loaded" } else if matches!(command, "install" | "start" | "restart") { "start_requested" } else { "stopped" },
            "message": if command == "register" { "Login startup is registered. The service has not been started." } else if matches!(command, "install" | "start") && inspected.loaded { "The login service was already loaded; this request did not restart it. Check status for readiness." } else if matches!(command, "install" | "start" | "restart") { "Background start requested. Check status for readiness." } else { "Background service stopped. Data is preserved." }}),
    )
}

#[cfg(any(test, target_os = "macos"))]
fn loaded_from_status(success: bool, code: Option<i32>) -> Result<bool, String> {
    if success {
        Ok(true)
    } else if code == Some(113) {
        Ok(false)
    } else {
        Err("Cannot confirm whether the background job is loaded; macOS inspection failed".into())
    }
}

#[cfg(not(target_os = "macos"))]
pub fn execute(_command: &str, _config_path: &Path) -> Result<serde_json::Value, String> {
    Err("Managed service installation is supported on macOS in this release; use run for a foreground service".into())
}

#[cfg(not(target_os = "macos"))]
fn execute_with_progress(
    command: &str,
    config_path: &Path,
    _progress: &dyn Fn(&str),
) -> Result<serde_json::Value, String> {
    execute(command, config_path)
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::*;
    #[test]
    fn failed_inspection_never_means_stopped() {
        assert_eq!(loaded_from_status(true, Some(0)).unwrap(), true);
        assert_eq!(loaded_from_status(false, Some(113)).unwrap(), false);
        assert!(loaded_from_status(false, Some(1)).is_err());
        assert!(loaded_from_status(false, None).is_err());
    }
    #[test]
    fn launch_agent_uses_owned_arguments_and_preserves_path_characters() {
        let config = ServerConfig::for_bundle(
            Path::new("/Applications/Magi Server"),
            "/Users/owner/Magi & data".into(),
        );
        let plist = launch_agent(
            Path::new("/Applications/Magi Server/magi-server"),
            Path::new("/Users/owner/config & service.json"),
            &config,
        )
        .unwrap();
        assert!(plist.contains("<string>/Applications/Magi Server/magi-server</string>"));
        assert!(plist.contains("config &amp; service.json"));
        assert!(plist.contains("Magi &amp; data/logs/service.log"));
        assert!(!plist.contains("StandardOutPath"));
        assert!(!plist.contains("StandardErrorPath"));
        assert!(!plist.contains("--bootstrap-stdin"));
        assert!(!plist.contains("/bin/sh"));
        assert!(plist.contains("<string>Aqua</string>"));
        use std::{
            io::Write,
            process::{Command, Stdio},
        };
        let mut validator = Command::new("/usr/bin/plutil")
            .args(["-lint", "-"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        validator
            .stdin
            .take()
            .unwrap()
            .write_all(plist.as_bytes())
            .unwrap();
        let output = validator.wait_with_output().unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
}
