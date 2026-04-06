use std::env;
use std::sync::Arc;

use magi_gateway::{api, ipc, notification_bridge};

/// Headless Magi gateway — serves HTTP on a given port and connects
/// to a running Python IPC worker.  No Tauri / desktop chrome required.
///
/// Environment variables:
///   MAGI_GATEWAY_PORT      — HTTP/WS listen port (default 19080)
///   MAGI_IPC_SOCKET        — Path to the Python IPC worker socket
///   MAGI_SESSION_TOKEN     — (optional) session token for authentication
#[tokio::main]
async fn main() {
    let port: u16 = env::var("MAGI_GATEWAY_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(19080);

    let ipc_socket = env::var("MAGI_IPC_SOCKET").unwrap_or_else(|_| {
        let home = env::var("HOME").unwrap_or_else(|_| ".".into());
        format!("{home}/.magi/runtime/ipc-gateway.sock")
    });

    eprintln!("Connecting to IPC worker at {ipc_socket}");
    let (ipc_client, _event_rx) =
        ipc::IpcClient::connect(&ipc_socket).await.unwrap_or_else(|e| {
            eprintln!("Failed to connect to IPC worker: {e}");
            std::process::exit(1);
        });
    let ipc_client = Arc::new(ipc_client);
    eprintln!("IPC connected");

    // Notification bridge — no Tauri event emitter in headless mode
    let (bridge_shutdown_tx, bridge_shutdown_rx) = tokio::sync::watch::channel(false);
    tokio::spawn(async move {
        notification_bridge::run_notification_bridge(None, bridge_shutdown_rx).await;
    });

    let state = api::state::ApiState {
        ipc_client,
    };
    let router = api::build_router(state);

    let listener = tokio::net::TcpListener::bind(("127.0.0.1", port))
        .await
        .unwrap_or_else(|e| {
            eprintln!("Failed to bind on port {port}: {e}");
            std::process::exit(1);
        });
    eprintln!("Magi gateway listening on http://127.0.0.1:{port}");

    // Write port file so benchmark scripts can auto-discover the gateway
    let port_file = std::path::PathBuf::from(
        env::var("HOME").unwrap_or_else(|_| ".".into()),
    )
    .join(".magi")
    .join("runtime")
    .join("gateway.port");
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
