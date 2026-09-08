use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use magi_server_runtime::config::{ServerConfig, WorkerLaunch};
use serde_json::{json, Value};

const TOKEN: &str = "integration-session-0123456789abcdef";

struct Server {
    child: Child,
    owner: Option<ChildStdin>,
    config_path: PathBuf,
    root: PathBuf,
    address: SocketAddr,
}

impl Server {
    fn start() -> Self {
        Self::start_mode(true)
    }

    fn start_mode(owned: bool) -> Self {
        let suffix = magi_gateway::api::security::generate_session_token();
        let root = std::env::temp_dir().join(format!("ms-{}", &suffix[..8]));
        let config_path = root.with_extension("json");
        let worker = std::env::current_exe().unwrap();
        let config = ServerConfig {
            data_dir: root.clone(),
            port: 0,
            builtin_avatar_dir: None,
            max_restarts: 1,
            startup_timeout_secs: 10,
            shutdown_timeout_secs: 2,
            worker: WorkerLaunch {
                executable: worker.clone(),
                plugin_python: worker,
                working_directory: None,
                python_path: vec![],
                args: vec![
                    "--ignored".into(),
                    "--exact".into(),
                    "fake_worker".into(),
                    "--nocapture".into(),
                ],
            },
        };
        fs::write(&config_path, serde_json::to_vec(&config).unwrap()).unwrap();
        let mut command = Command::new(env!("CARGO_BIN_EXE_magi-server"));
        command.args(["run", "--config"]).arg(&config_path);
        if owned {
            command.arg("--bootstrap-stdin");
        }
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap();
        let mut owner = child.stdin.take().unwrap();
        if owned {
            writeln!(owner, "{}", json!({"session_token": TOKEN})).unwrap();
            owner.flush().unwrap();
        }
        let stdout = child.stdout.take().unwrap();
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            let mut line = String::new();
            let _ = BufReader::new(stdout).read_line(&mut line);
            let _ = tx.send(line);
        });
        let line = rx
            .recv_timeout(Duration::from_secs(10))
            .unwrap_or_else(|error| {
                let _ = child.kill();
                let _ = child.wait();
                panic!("Server did not publish its listener: {error}");
            });
        let info: Value = serde_json::from_str(&line).unwrap();
        let address = info["baseUrl"]
            .as_str()
            .unwrap()
            .strip_prefix("http://")
            .unwrap()
            .strip_suffix("/api")
            .unwrap()
            .parse()
            .unwrap();
        Self {
            child,
            owner: Some(owner),
            config_path,
            root,
            address,
        }
    }

    fn get(&self, path: &str, authenticated: bool) -> String {
        let mut stream = TcpStream::connect_timeout(&self.address, Duration::from_secs(1)).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        let credential = if authenticated {
            format!("x-magi-session-token: {TOKEN}\r\n")
        } else {
            String::new()
        };
        write!(
            stream,
            "GET {path} HTTP/1.1\r\nHost: {}\r\n{credential}Connection: close\r\n\r\n",
            self.address
        )
        .unwrap();
        let mut response = String::new();
        stream.read_to_string(&mut response).unwrap();
        response
    }

    fn wait_ready(&self) {
        let deadline = Instant::now() + Duration::from_secs(10);
        while Instant::now() < deadline {
            if self.get("/api/ready", true).contains("\"ready\":true") {
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        panic!("Worker never became ready");
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        self.owner.take();
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if self.child.try_wait().ok().flatten().is_some() {
                break;
            }
            std::thread::sleep(Duration::from_millis(25));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = fs::remove_dir_all(&self.root);
        let _ = fs::remove_file(&self.config_path);
    }
}

#[test]
fn server_owns_worker_without_tauri_and_rejects_duplicate_instance() {
    let mut server = Server::start();
    assert!(server.get("/api/health", false).starts_with("HTTP/1.1 200"));
    assert!(server.get("/api/tasks", false).starts_with("HTTP/1.1 401"));
    assert!(server.get("/api/tasks", true).starts_with("HTTP/1.1 503"));
    server.wait_ready();
    let duplicate = Command::new(env!("CARGO_BIN_EXE_magi-server"))
        .args(["run", "--config"])
        .arg(&server.config_path)
        .output()
        .unwrap();
    assert!(!duplicate.status.success());
    assert!(String::from_utf8_lossy(&duplicate.stderr).contains("already running"));
    server.owner.take();
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if let Some(status) = server.child.try_wait().unwrap() {
            assert!(status.success());
            break;
        }
        assert!(
            Instant::now() < deadline,
            "Server outlived its desktop owner"
        );
        std::thread::sleep(Duration::from_millis(25));
    }
    assert!(!server.root.join("runtime/worker.ready").exists());
}

#[test]
fn worker_crash_reconnects_without_restarting_gateway() {
    let server = Server::start();
    server.wait_ready();
    let original_pid = fs::read_to_string(server.root.join("runtime/worker.ready")).unwrap();
    fs::write(server.root.join("crash-on-request"), b"").unwrap();
    let _ = server.get("/api/ready", true);
    let deadline = Instant::now() + Duration::from_secs(12);
    loop {
        let pid = fs::read_to_string(server.root.join("runtime/worker.ready")).ok();
        if pid.as_ref().is_some_and(|pid| pid != &original_pid) {
            break;
        }
        assert!(Instant::now() < deadline, "Worker did not restart");
        std::thread::sleep(Duration::from_millis(50));
    }
    server.wait_ready();
}

#[cfg(unix)]
#[test]
fn unowned_console_server_supports_private_operator_pairing() {
    let server = Server::start_mode(false);
    assert!(server
        .get("/api/server/info", true)
        .starts_with("HTTP/1.1 401"));
    let operator = |command: &str| {
        let output = Command::new(env!("CARGO_BIN_EXE_magi-server"))
            .arg(command)
            .arg("--config")
            .arg(&server.config_path)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        serde_json::from_slice::<Value>(&output.stdout).unwrap()
    };
    let status = operator("status");
    let pairing = operator("pair");
    assert_eq!(status["server_id"], pairing["server_id"]);
    assert_eq!(pairing["pairing_token"].as_str().unwrap().len(), 64);
    assert_eq!(operator("clients"), json!([]));
    let database = fs::read(server.root.join("service/server.db")).unwrap();
    assert!(!database
        .windows(64)
        .any(|part| part == pairing["pairing_token"].as_str().unwrap().as_bytes()));
    // SIGTERM requests graceful exit of the child owned by this test.
    signal_terminate(server.child.id());
}

#[cfg(unix)]
fn signal_terminate(pid: u32) {
    // Avoid a test-only libc dependency; the platform kill command targets only this child.
    let status = Command::new("/bin/kill")
        .args(["-TERM", &pid.to_string()])
        .status()
        .unwrap();
    assert!(status.success());
}

// This test executable acts as the child fixture; it is never part of the product.
#[test]
#[ignore]
fn fake_worker() {
    let root = PathBuf::from(std::env::var_os("MAGI_HOME").unwrap());
    let _lease =
        magi_server_runtime::instance::InstanceLease::acquire(&root.join("runtime/worker.lock"))
            .unwrap();
    std::thread::sleep(Duration::from_millis(750));
    let socket = std::env::var("MAGI_IPC_SOCKET").unwrap();
    #[cfg(unix)]
    let listener = std::os::unix::net::UnixListener::bind(socket).unwrap();
    #[cfg(not(unix))]
    let listener = std::net::TcpListener::bind(socket).unwrap();
    fs::write(
        root.join("runtime/worker.ready"),
        std::process::id().to_string(),
    )
    .unwrap();
    let (mut stream, _) = listener.accept().unwrap();
    let mut reader = BufReader::new(stream.try_clone().unwrap());
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line).unwrap() == 0 {
            break;
        }
        let request: Value = serde_json::from_str(&line).unwrap();
        if root.join("crash-on-request").exists() {
            fs::remove_file(root.join("crash-on-request")).unwrap();
            std::process::exit(31);
        }
        let result = if request["method"] == "ipc.authenticate" {
            assert_eq!(
                request["params"]["token"],
                std::env::var("MAGI_IPC_AUTH_TOKEN").unwrap()
            );
            json!({"authenticated": true})
        } else {
            json!({"success": true, "data": {"ready": true, "runtime_ready": true}})
        };
        writeln!(stream, "{}", json!({"id": request["id"], "result": result})).unwrap();
        stream.flush().unwrap();
    }
}
