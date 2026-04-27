//! Integration tests for the magi-gateway router.
//!
//! These tests verify that the Axum router builds correctly and that
//! endpoints not requiring IPC (health, ready) respond as expected.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;

use axum::body::Body;
use http_body_util::BodyExt;
use hyper::Request;
use magi_gateway::{api, ipc};
use serde_json::Value;
use tower::ServiceExt;

static TEST_COUNTER: AtomicU32 = AtomicU32::new(0);

struct HomeGuard {
    previous: Option<OsString>,
    home: PathBuf,
}

impl HomeGuard {
    fn path(&self) -> &Path {
        &self.home
    }
}

impl Drop for HomeGuard {
    fn drop(&mut self) {
        if let Some(previous) = &self.previous {
            std::env::set_var("HOME", previous);
        } else {
            std::env::remove_var("HOME");
        }
    }
}

fn isolated_home(label: &str) -> HomeGuard {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let home = std::env::temp_dir().join(format!(
        "magi-gateway-home-{label}-{}-{n}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(&home).unwrap();
    let previous = std::env::var_os("HOME");
    std::env::set_var("HOME", &home);
    HomeGuard { previous, home }
}

async fn request_json(
    router: axum::Router,
    method: &str,
    uri: &str,
    body: Option<&str>,
) -> (u16, Value) {
    let mut builder = Request::builder().method(method).uri(uri);
    if body.is_some() {
        builder = builder.header("content-type", "application/json");
    }
    let request_body = body
        .map(|content| Body::from(content.to_owned()))
        .unwrap_or_else(Body::empty);
    let response = router
        .oneshot(builder.body(request_body).unwrap())
        .await
        .unwrap();
    let status = response.status().as_u16();
    let body = response.into_body().collect().await.unwrap().to_bytes();
    let json = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&body).unwrap()
    };
    (status, json)
}

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
    assert!(json["data"]["startup_state"].is_string());
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

#[tokio::test]
async fn native_read_routes_return_stable_empty_payloads_when_databases_are_missing() {
    let _home = isolated_home("missing-dbs");
    let state = test_state().await;
    let router = api::build_router(state);

    let (status, tasks) = request_json(router.clone(), "GET", "/api/tasks?user_id=u1", None).await;
    assert_eq!(status, 200);
    assert_eq!(tasks["tasks"].as_array().unwrap().len(), 0);

    let (status, schedules) = request_json(router.clone(), "GET", "/api/schedules", None).await;
    assert_eq!(status, 200);
    assert_eq!(schedules["schedules"].as_array().unwrap().len(), 0);

    let (status, events) = request_json(
        router,
        "GET",
        "/api/memory/l1/events?limit=7&offset=3",
        None,
    )
    .await;
    assert_eq!(status, 200);
    assert_eq!(events["items"].as_array().unwrap().len(), 0);
    assert_eq!(events["total"], 0);
    assert_eq!(events["limit"], 7);
    assert_eq!(events["offset"], 3);
}

#[tokio::test]
async fn native_task_create_persists_owned_product_fields() {
    let home = isolated_home("task-create");
    let runtime_dir = home.path().join(".magi").join("runtime");
    std::fs::create_dir_all(&runtime_dir).unwrap();
    let conn = rusqlite::Connection::open(runtime_dir.join("tasks.db")).unwrap();
    conn.execute_batch(
        "CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            due_date REAL,
            created_by TEXT NOT NULL,
            user_id TEXT NOT NULL,
            session_id TEXT,
            linked_orchestration_id TEXT,
            linked_turn_id TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );",
    )
    .unwrap();
    drop(conn);

    let state = test_state().await;
    let router = api::build_router(state);
    let (status, created) = request_json(
        router.clone(),
        "POST",
        "/api/tasks?user_id=u1",
        Some(
            r#"{
                "title":"Review memory evidence",
                "description":"Check the Alpha trace path",
                "priority":"high",
                "tags":["alpha","memory"],
                "linked_orchestration_id":"orch-1",
                "linked_turn_id":"turn-1"
            }"#,
        ),
    )
    .await;

    assert_eq!(status, 201);
    let task_id = created["task"]["task_id"].as_str().unwrap();
    assert_eq!(created["task"]["title"], "Review memory evidence");
    assert_eq!(created["task"]["status"], "open");
    assert_eq!(created["task"]["priority"], "high");
    assert_eq!(
        created["task"]["tags"],
        serde_json::json!(["alpha", "memory"])
    );

    let (status, fetched) =
        request_json(router, "GET", &format!("/api/tasks/{task_id}"), None).await;
    assert_eq!(status, 200);
    assert_eq!(fetched["task"]["task_id"], task_id);
    assert_eq!(fetched["task"]["user_id"], "u1");
}
