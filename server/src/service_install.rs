//! User-session service installation. Business data is never removed here.

#[cfg(target_os = "macos")]
use magi_server_runtime::config::ServerConfig;
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
fn launch_agent(
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
<key>ProgramArguments</key><array><string>{}</string><string>run</string><string>--config</string><string>{}</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>30</integer>
<key>ExitTimeOut</key><integer>45</integer>
<key>ProcessType</key><string>Background</string>
<key>LimitLoadToSessionType</key><string>Aqua</string>
<key>Umask</key><integer>63</integer>
<key>StandardOutPath</key><string>{}</string>
<key>StandardErrorPath</key><string>{}</string>
</dict></plist>
"#,
        text(executable)?,
        text(config_path)?,
        text(&config.data_dir.join("logs/service.stdout.log"))?,
        text(&config.data_dir.join("logs/service.stderr.log"))?
    ))
}

#[cfg(target_os = "macos")]
pub fn execute(command: &str, config_path: &Path) -> Result<(), String> {
    use std::{
        fs,
        io::Write,
        os::unix::fs::{MetadataExt, OpenOptionsExt},
        process::Command,
    };
    let config_path = config_path.canonicalize().map_err(|e| e.to_string())?;
    let config = ServerConfig::load(&config_path)?;
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let expected = launch_agent(&executable, &config_path, &config)?;
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
    let launchctl = |args: &[&str]| -> Result<(), String> {
        let output = Command::new("/bin/launchctl")
            .args(args)
            .output()
            .map_err(|e| e.to_string())?;
        if output.status.success() {
            Ok(())
        } else {
            Err(format!(
                "launchctl failed: {}",
                String::from_utf8_lossy(&output.stderr).trim()
            ))
        }
    };
    let loaded = || -> Result<bool, String> {
        Ok(Command::new("/bin/launchctl")
            .args(["print", &target])
            .output()
            .map_err(|e| e.to_string())?
            .status
            .success())
    };
    if command == "install" {
        fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
        if !plist.exists() {
            // Pre-create the log directory before launchd opens standard streams.
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
        "install" | "start" => {
            if !loaded()? {
                launchctl(&["enable", &target])?;
                launchctl(&["bootstrap", &domain, plist_arg])?;
            }
        }
        "stop" | "uninstall" => {
            if loaded()? {
                launchctl(&["bootout", &target])?;
            }
            if command == "uninstall" {
                fs::remove_file(&plist).map_err(|e| e.to_string())?;
            }
        }
        "restart" => {
            if loaded()? {
                launchctl(&["bootout", &target])?;
            }
            launchctl(&["enable", &target])?;
            launchctl(&["bootstrap", &domain, plist_arg])?;
        }
        _ => return Err("Unknown service installation command".into()),
    }
    println!(
        "{}",
        serde_json::json!({"command":command,"launch_agent":plist,"data_dir":config.data_dir,"data_preserved":true})
    );
    Ok(())
}

#[cfg(not(target_os = "macos"))]
pub fn execute(_command: &str, _config_path: &Path) -> Result<(), String> {
    Err("Managed service installation is supported on macOS in this release; use run for a foreground service".into())
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::*;
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
        assert!(plist.contains("Magi &amp; data/logs/service.stderr.log"));
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
