//! Integration tests for the magi-gateway router.
//!
//! These tests verify that the Axum router builds correctly and that
//! endpoints not requiring IPC (health, ready) respond as expected.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;

use axum::body::Body;
use http_body_util::BodyExt;
use hyper::Request;
use magi_gateway::{api, ipc};
use serde_json::Value;
use tower::ServiceExt;

static TEST_COUNTER: AtomicU32 = AtomicU32::new(0);

/// Create a test ApiState using a real temporary socket pair.
async fn test_state() -> api::state::ApiState {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let sock_path = std::env::temp_dir().join(format!("magi-test-{}-{n}.sock", std::process::id()));
    let _ = std::fs::remove_file(&sock_path);

    let listener = tokio::net::UnixListener::bind(&sock_path).unwrap();

    // Spawn a dummy server that accepts but never responds
    tokio::spawn(async move {
        loop {
            if let Ok((mut stream, _)) = listener.accept().await {
                tokio::spawn(async move {
                    let _ = tokio::io::AsyncReadExt::read(&mut stream, &mut [0u8; 1024]).await;
                });
            }
        }
    });

    tokio::task::yield_now().await;

    let (ipc_client, _event_rx) = ipc::IpcClient::connect(sock_path.to_str().unwrap())
        .await
        .expect("Connect to test IPC socket");

    api::state::ApiState {
        ipc_client: Arc::new(ipc_client),
        builtin_avatar_dir: None,
        user_avatar_dir: None,
    }
}

#[tokio::test]
async fn health_returns_ok() {
    let state = test_state().await;
    let router = api::build_router(state);

    let req = Request::builder()
        .uri("/api/health")
        .body(Body::empty())
        .unwrap();

    let response = router.oneshot(req).await.unwrap();

    assert_eq!(response.status(), 200);

    let body = response.into_body().collect().await.unwrap().to_bytes();
    let json: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(json["status"], "ok");
}

#[tokio::test]
async fn ready_returns_json() {
    let state = test_state().await;
    let router = api::build_router(state);

    let req = Request::builder()
        .uri("/api/ready")
        .body(Body::empty())
        .unwrap();

    let response = router.oneshot(req).await.unwrap();

    assert_eq!(response.status(), 200);

    let body = response.into_body().collect().await.unwrap().to_bytes();
    let json: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(json["success"], true);
    assert!(json["data"]["ready"].is_boolean());
}

#[tokio::test]
async fn unknown_api_path_hits_fallback_proxy() {
    let state = test_state().await;
    let router = api::build_router(state);

    let req = Request::builder()
        .uri("/api/nonexistent")
        .body(Body::empty())
        .unwrap();

    let response = router.oneshot(req).await.unwrap();

    // The proxy will try IPC and fail/timeout — we just verify it doesn't 404
    // at the Axum routing level (the fallback handler should catch it).
    // The response might be 502 or similar since the dummy IPC won't respond.
    let status = response.status().as_u16();
    // Should NOT be 404 (Axum's default for unmatched routes)
    // The proxy handler should intercept it
    assert_ne!(
        status, 404,
        "Fallback proxy should handle unknown /api/ paths"
    );
}

#[tokio::test]
async fn cors_headers_present() {
    let state = test_state().await;
    let router = api::build_router(state);

    let req = Request::builder()
        .method("OPTIONS")
        .uri("/api/health")
        .header("Origin", "http://localhost:1420")
        .header("Access-Control-Request-Method", "GET")
        .body(Body::empty())
        .unwrap();

    let response = router.oneshot(req).await.unwrap();

    assert!(
        response
            .headers()
            .contains_key("access-control-allow-origin"),
        "CORS allow-origin header should be present"
    );
}
