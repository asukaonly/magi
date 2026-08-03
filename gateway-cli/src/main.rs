use std::env;
use std::path::PathBuf;
use std::sync::Arc;

use magi_gateway::{api, db, ipc, notification_bridge};

fn home_dir_from_values(
    home: Option<&std::ffi::OsStr>,
    user_profile: Option<&std::ffi::OsStr>,
) -> Result<PathBuf, String> {
    home.filter(|value| !value.is_empty())
        .or_else(|| user_profile.filter(|value| !value.is_empty()))
        .map(PathBuf::from)
        .ok_or_else(|| "Neither HOME nor USERPROFILE is set".to_string())
}

fn home_dir() -> Result<PathBuf, String> {
    let home = env::var_os("HOME");
    let user_profile = env::var_os("USERPROFILE");
    home_dir_from_values(home.as_deref(), user_profile.as_deref())
}

fn resolve_ipc_socket(
    configured: Option<&str>,
    home: &std::path::Path,
    is_windows: bool,
) -> Result<String, String> {
    if let Some(value) = configured {
        let value = value.trim();
        if value.is_empty() {
            return Err("MAGI_IPC_SOCKET must not be empty".to_string());
        }
        return Ok(value.to_string());
    }
    if is_windows {
        return Err("MAGI_IPC_SOCKET is required on Windows".to_string());
    }
    Ok(home
        .join(".magi")
        .join("runtime")
        .join("ipc.sock")
        .to_string_lossy()
        .into_owned())
}

fn configured_ipc_socket(home: &std::path::Path) -> Result<String, String> {
    match env::var("MAGI_IPC_SOCKET") {
        Ok(value) => resolve_ipc_socket(Some(&value), home, cfg!(windows)),
        Err(env::VarError::NotPresent) => resolve_ipc_socket(None, home, cfg!(windows)),
        Err(env::VarError::NotUnicode(_)) => Err("MAGI_IPC_SOCKET must be valid text".to_string()),
    }
}

fn required_session_token(value: Option<String>) -> Result<String, String> {
    value
        .map(|token| token.trim().to_string())
        .filter(|token| !token.is_empty())
        .ok_or_else(|| "MAGI_DESKTOP_SESSION_TOKEN is required".to_string())
}

fn required_ipc_auth_token(value: Option<String>) -> Result<String, String> {
    value
        .map(|token| token.trim().to_string())
        .filter(|token| !token.is_empty())
        .ok_or_else(|| "MAGI_IPC_AUTH_TOKEN is required".to_string())
}

fn resolve_user_avatar_dir(home: &std::path::Path) -> Option<PathBuf> {
    let dir = home.join(".magi").join("personalities").join("avatar");
    let _ = std::fs::create_dir_all(&dir);
    Some(dir)
}

/// Headless Magi gateway — serves HTTP on a given port and connects
/// to a running Python IPC worker.  No Tauri / desktop chrome required.
///
/// Environment variables:
///   MAGI_GATEWAY_PORT      — HTTP/WS listen port (default 19080)
///   MAGI_IPC_SOCKET        — Path to the Python IPC worker socket
///   MAGI_DESKTOP_SESSION_TOKEN — required session token for authentication
///   MAGI_IPC_AUTH_TOKEN    — required credential for the Python IPC worker
#[tokio::main]
async fn main() {
    let port: u16 = env::var("MAGI_GATEWAY_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(19080);

    let home = home_dir().unwrap_or_else(|error| {
        eprintln!("{error}");
        std::process::exit(2);
    });
    let ipc_socket = configured_ipc_socket(&home).unwrap_or_else(|error| {
        eprintln!("{error}");
        std::process::exit(2);
    });
    let session_token = required_session_token(env::var("MAGI_DESKTOP_SESSION_TOKEN").ok())
        .unwrap_or_else(|error| {
            eprintln!("{error}");
            std::process::exit(2);
        });
    let ipc_auth_token = required_ipc_auth_token(env::var("MAGI_IPC_AUTH_TOKEN").ok())
        .unwrap_or_else(|error| {
            eprintln!("{error}");
            std::process::exit(2);
        });

    eprintln!("Connecting to IPC worker at {ipc_socket}");
    let (ipc_client, _event_rx) = ipc::IpcClient::connect(&ipc_socket, &ipc_auth_token)
        .await
        .unwrap_or_else(|e| {
            eprintln!("Failed to connect to IPC worker: {e}");
            std::process::exit(1);
        });
    let ipc_client = Arc::new(ipc_client);
    eprintln!("IPC connected");

    // Ensure performance-critical indexes exist on SQLite databases
    db::ensure_indexes();

    // Notification bridge — no Tauri event emitter in headless mode
    let (bridge_shutdown_tx, bridge_shutdown_rx) = tokio::sync::watch::channel(false);
    tokio::spawn(async move {
        notification_bridge::run_notification_bridge(None, bridge_shutdown_rx).await;
    });

    let security = Arc::new(api::security::GatewaySecurity::new(session_token));
    let state = api::state::ApiState::new(ipc_client, security)
        .with_avatar_dirs(None, resolve_user_avatar_dir(&home));
    let router = api::build_router(state);

    let listener = tokio::net::TcpListener::bind(("127.0.0.1", port))
        .await
        .unwrap_or_else(|e| {
            eprintln!("Failed to bind on port {port}: {e}");
            std::process::exit(1);
        });
    eprintln!("Magi gateway listening on http://127.0.0.1:{port}");

    // Write port file so benchmark scripts can auto-discover the gateway
    let port_file = home.join(".magi").join("runtime").join("gateway.port");
    let _ = std::fs::create_dir_all(port_file.parent().unwrap());
    let _ = std::fs::write(&port_file, port.to_string());

    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel::<()>();

    // Ctrl-C handler
    tokio::spawn(async move {
        tokio::signal::ctrl_c().await.ok();
        eprintln!("\nShutting down...");
        let _ = shutdown_tx.send(());
    });

    magi_gateway::axum::serve(listener, router)
        .with_graceful_shutdown(async {
            let _ = shutdown_rx.await;
        })
        .await
        .ok();

    let _ = bridge_shutdown_tx.send(true);
    let _ = std::fs::remove_file(&port_file);
    eprintln!("Gateway stopped");
}

#[cfg(test)]
mod tests {
    use super::{
        home_dir_from_values, required_ipc_auth_token, required_session_token, resolve_ipc_socket,
    };
    use std::ffi::OsStr;
    use std::path::{Path, PathBuf};

    #[test]
    fn home_dir_prefers_home_and_falls_back_to_user_profile() {
        assert_eq!(
            home_dir_from_values(
                Some(OsStr::new("/home/primary")),
                Some(OsStr::new("C:\\Users\\fallback"))
            )
            .unwrap(),
            PathBuf::from("/home/primary")
        );
        assert_eq!(
            home_dir_from_values(None, Some(OsStr::new("C:\\Users\\fallback"))).unwrap(),
            PathBuf::from("C:\\Users\\fallback")
        );
        assert!(home_dir_from_values(None, None).is_err());
        assert!(home_dir_from_values(Some(OsStr::new("")), Some(OsStr::new(""))).is_err());
    }

    #[test]
    fn ipc_socket_defaults_only_on_unix() {
        let home = Path::new("/home/tester");
        assert_eq!(
            resolve_ipc_socket(None, home, false).unwrap(),
            "/home/tester/.magi/runtime/ipc.sock"
        );
        assert!(resolve_ipc_socket(None, home, true).is_err());
    }

    #[test]
    fn explicit_ipc_socket_is_required_to_be_non_empty() {
        let home = Path::new("/unused");
        assert_eq!(
            resolve_ipc_socket(Some("127.0.0.1:19081"), home, true).unwrap(),
            "127.0.0.1:19081"
        );
        assert!(resolve_ipc_socket(Some("  "), home, false).is_err());
    }

    #[test]
    fn session_token_is_required_and_trimmed() {
        assert_eq!(
            required_session_token(Some("  external-session  ".to_string())).unwrap(),
            "external-session"
        );
        assert!(required_session_token(None).is_err());
        assert!(required_session_token(Some("  ".to_string())).is_err());
    }

    #[test]
    fn ipc_auth_token_is_required_and_trimmed() {
        assert_eq!(
            required_ipc_auth_token(Some("  internal-secret  ".to_string())).unwrap(),
            "internal-secret"
        );
        assert!(required_ipc_auth_token(None).is_err());
        assert!(required_ipc_auth_token(Some("  ".to_string())).is_err());
    }
}
