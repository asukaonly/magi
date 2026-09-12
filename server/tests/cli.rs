use std::{fs, path::PathBuf, process::Command};

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let id = magi_gateway::api::security::generate_session_token();
        let root = std::env::temp_dir().join(format!("magi-cli-{}", &id[..12]));
        fs::create_dir_all(root.join("bundle/sidecar-dist")).unwrap();
        fs::write(
            root.join(if cfg!(windows) {
                "bundle/sidecar-dist/magi-backend.exe"
            } else {
                "bundle/sidecar-dist/magi-backend"
            }),
            b"fixture",
        )
        .unwrap();
        let plugin = root.join(if cfg!(windows) {
            "bundle/plugin-python/python.exe"
        } else {
            "bundle/plugin-python/bin/python"
        });
        fs::create_dir_all(plugin.parent().unwrap()).unwrap();
        fs::write(plugin, b"fixture").unwrap();
        Self(root)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn packaged_init_uses_bundle_paths_and_refuses_overwriting_config() {
    let fixture = Fixture::new();
    let config = fixture.0.join("config/server.json");
    let data = fixture.0.join("data");
    let bundle = fixture.0.join("bundle");
    let args = [
        "init",
        "--config",
        config.to_str().unwrap(),
        "--data-dir",
        data.to_str().unwrap(),
        "--bundle-root",
        bundle.to_str().unwrap(),
        "--port",
        "19123",
    ];
    let result = Command::new(env!("CARGO_BIN_EXE_magi-server"))
        .args(args)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let original = fs::read(&config).unwrap();
    let parsed: serde_json::Value = serde_json::from_slice(&original).unwrap();
    assert_eq!(parsed["data_dir"], data.to_str().unwrap());
    assert_eq!(parsed["port"], 19123);
    assert_eq!(parsed["worker"]["python_path"], serde_json::json!([]));
    assert!(!String::from_utf8_lossy(&original).contains("development"));
    let repeated = Command::new(env!("CARGO_BIN_EXE_magi-server"))
        .args(args)
        .output()
        .unwrap();
    assert!(!repeated.status.success());
    assert_eq!(fs::read(&config).unwrap(), original);
    assert!(!data.exists());
    for command in ["show", "validate"] {
        let inspected = Command::new(env!("CARGO_BIN_EXE_magi-server"))
            .args(["config", command, "--config"])
            .arg(&config)
            .env_remove("HOME")
            .env_remove("USERPROFILE")
            .output()
            .unwrap();
        assert!(
            inspected.status.success(),
            "{}",
            String::from_utf8_lossy(&inspected.stderr)
        );
        assert!(!data.exists());
        assert_eq!(fs::read(&config).unwrap(), original);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(&config).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
}

#[test]
fn console_version_and_help_do_not_require_a_configuration() {
    let version = Command::new(env!("CARGO_BIN_EXE_magi-server"))
        .arg("--version")
        .output()
        .unwrap();
    assert!(version.status.success());
    assert!(String::from_utf8_lossy(&version.stdout).contains(env!("CARGO_PKG_VERSION")));
    assert!(String::from_utf8_lossy(&version.stdout).contains(&format!(
        "protocol {}",
        magi_service_contract::SERVER_PROTOCOL_VERSION
    )));
    let help = Command::new(env!("CARGO_BIN_EXE_magi-server"))
        .arg("--help")
        .output()
        .unwrap();
    assert!(help.status.success());
    assert!(String::from_utf8_lossy(&help.stdout).contains("--bundle-root"));
}

#[test]
fn default_entry_refuses_noninteractive_input_without_creating_data() {
    let fixture = Fixture::new();
    let path = fixture.0.join("never-created.json");
    let result = Command::new(env!("CARGO_BIN_EXE_magi-server"))
        .arg("--config")
        .arg(&path)
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("requires a terminal"));
    assert!(!path.exists());
}

#[test]
fn explicit_commands_reject_invalid_or_misplaced_arguments() {
    for args in [
        vec!["revoke"],
        vec!["run", "--port", "1234"],
        vec!["init", "--port", "65536"],
        vec!["configure", "--api-key", "secret"],
        vec!["run", "--bootstrap-stdin", "--shutdown-on-stdin-close"],
    ] {
        assert!(!Command::new(env!("CARGO_BIN_EXE_magi-server"))
            .args(args)
            .output()
            .unwrap()
            .status
            .success());
    }
}

#[cfg(unix)]
#[test]
fn managed_output_captures_startup_failures_without_changing_console_output() {
    let fixture = Fixture::new();
    let config = fixture.0.join("missing.json");
    let log = fixture.0.join("logs/service.log");
    let result = Command::new(env!("CARGO_BIN_EXE_magi-server"))
        .args(["run", "--config"])
        .arg(&config)
        .arg("--log-file")
        .arg(&log)
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert!(result.stdout.is_empty());
    assert!(result.stderr.is_empty());
    assert!(!fs::read(&log).unwrap().is_empty());
    use std::os::unix::fs::PermissionsExt;
    assert_eq!(
        fs::metadata(log.parent().unwrap())
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o700,
    );
    // Every run owns log initialization, including restarts after a log cleanup.
    fs::remove_dir_all(log.parent().unwrap()).unwrap();
    let restarted = Command::new(env!("CARGO_BIN_EXE_magi-server"))
        .args(["run", "--config"])
        .arg(&config)
        .arg("--log-file")
        .arg(&log)
        .output()
        .unwrap();
    assert!(!restarted.status.success());
    assert!(restarted.stderr.is_empty());
    assert!(!fs::read(&log).unwrap().is_empty());
    let console = Command::new(env!("CARGO_BIN_EXE_magi-server"))
        .args(["run", "--config"])
        .arg(&config)
        .output()
        .unwrap();
    assert!(!console.status.success());
    assert!(!console.stderr.is_empty());

    let desktop = Command::new(env!("CARGO_BIN_EXE_magi-server"))
        .args(["run", "--bootstrap-stdin", "--config"])
        .arg(&config)
        .arg("--log-file")
        .arg(fixture.0.join("desktop.log"))
        .output()
        .unwrap();
    assert!(!desktop.status.success());
    assert!(desktop.stderr.is_empty());
    assert!(!fs::read(fixture.0.join("desktop.log")).unwrap().is_empty());
}
