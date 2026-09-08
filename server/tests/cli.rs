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
    let help = Command::new(env!("CARGO_BIN_EXE_magi-server"))
        .arg("--help")
        .output()
        .unwrap();
    assert!(help.status.success());
    assert!(String::from_utf8_lossy(&help.stdout).contains("--bundle-root"));
}
