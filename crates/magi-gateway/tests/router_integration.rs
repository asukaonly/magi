//! Integration tests for the magi-gateway router.
//!
//! These tests verify that the Axum router builds correctly and that
//! endpoints not requiring IPC (health, ready) respond as expected.

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, OnceLock};

use axum::body::Body;
use http_body_util::BodyExt;
use hyper::Request;
use magi_gateway::{api, db, ipc};
use serde_json::Value;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tower::ServiceExt;

static TEST_COUNTER: AtomicU32 = AtomicU32::new(0);
static HOME_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
const TEST_SESSION_TOKEN: &str = "test-desktop-session-token";

fn test_security() -> Arc<api::security::GatewaySecurity> {
    Arc::new(api::security::GatewaySecurity::with_policy(
        TEST_SESSION_TOKEN,
        [
            "http://127.0.0.1:5173",
            "tauri://localhost",
            "http://tauri.localhost",
        ],
        std::time::Duration::from_secs(60),
        128,
    ))
}

struct HomeGuard {
    previous_base_dir: Option<PathBuf>,
    home: PathBuf,
    _lock: MutexGuard<'static, ()>,
}

impl HomeGuard {
    fn path(&self) -> &Path {
        &self.home
    }
}

impl Drop for HomeGuard {
    fn drop(&mut self) {
        db::set_magi_base_dir_override_for_tests(self.previous_base_dir.take());
    }
}

fn isolated_home(label: &str) -> HomeGuard {
    let lock = router_test_guard();
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let home = std::env::temp_dir().join(format!(
        "magi-gateway-home-{label}-{}-{n}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(&home).unwrap();
    let previous_base_dir = db::set_magi_base_dir_override_for_tests(Some(home.join(".magi")));
    HomeGuard {
        previous_base_dir,
        home,
        _lock: lock,
    }
}

fn router_test_guard() -> MutexGuard<'static, ()> {
    HOME_LOCK
        .get_or_init(|| Mutex::new(()))
        .lock()
        .expect("lock gateway router integration test")
}

fn staged_ipc_body_paths() -> HashSet<PathBuf> {
    std::fs::read_dir(std::env::temp_dir())
        .into_iter()
        .flatten()
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.starts_with("magi-ipc-body-"))
        })
        .collect()
}

async fn request_json(
    router: axum::Router,
    method: &str,
    uri: &str,
    body: Option<&str>,
) -> (u16, Value) {
    let mut builder = Request::builder().method(method).uri(uri);
    builder = builder.header(api::security::SESSION_TOKEN_HEADER, TEST_SESSION_TOKEN);
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
#[cfg(unix)]
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

    api::state::ApiState::new(Arc::new(ipc_client), test_security())
}

#[cfg(unix)]
async fn test_state_with_runtime_ready_response(result: Value) -> api::state::ApiState {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let sock_path =
        std::env::temp_dir().join(format!("magi-test-ready-{}-{n}.sock", std::process::id()));
    let _ = std::fs::remove_file(&sock_path);

    let listener = tokio::net::UnixListener::bind(&sock_path).unwrap();
    tokio::spawn(async move {
        loop {
            if let Ok((stream, _)) = listener.accept().await {
                let result = result.clone();
                tokio::spawn(async move {
                    let (reader, mut writer) = stream.into_split();
                    let mut lines = BufReader::new(reader).lines();
                    while let Ok(Some(line)) = lines.next_line().await {
                        let request: Value = serde_json::from_str(&line).unwrap();
                        assert_eq!(request["method"], "runtime.ready");
                        let response = serde_json::json!({
                            "id": request["id"],
                            "result": result,
                        });
                        writer
                            .write_all(format!("{}\n", response).as_bytes())
                            .await
                            .unwrap();
                        writer.flush().await.unwrap();
                    }
                });
            }
        }
    });

    tokio::task::yield_now().await;

    let (ipc_client, _event_rx) = ipc::IpcClient::connect(sock_path.to_str().unwrap())
        .await
        .expect("Connect to test IPC socket");

    api::state::ApiState::new(Arc::new(ipc_client), test_security())
}

#[cfg(unix)]
async fn test_state_with_api_forward_response(
    result: Value,
) -> (api::state::ApiState, Arc<Mutex<Vec<Value>>>) {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let sock_path =
        std::env::temp_dir().join(format!("magi-test-forward-{}-{n}.sock", std::process::id()));
    let _ = std::fs::remove_file(&sock_path);
    let listener = tokio::net::UnixListener::bind(&sock_path).unwrap();
    let requests = Arc::new(Mutex::new(Vec::new()));
    let observed = Arc::clone(&requests);
    tokio::spawn(async move {
        loop {
            if let Ok((stream, _)) = listener.accept().await {
                let result = result.clone();
                let observed = Arc::clone(&observed);
                tokio::spawn(async move {
                    let (reader, mut writer) = stream.into_split();
                    let mut lines = BufReader::new(reader).lines();
                    while let Ok(Some(line)) = lines.next_line().await {
                        let request: Value = serde_json::from_str(&line).unwrap();
                        observed.lock().unwrap().push(request.clone());
                        let response = serde_json::json!({
                            "id": request["id"],
                            "result": result,
                        });
                        writer
                            .write_all(format!("{}\n", response).as_bytes())
                            .await
                            .unwrap();
                        writer.flush().await.unwrap();
                    }
                });
            }
        }
    });

    tokio::task::yield_now().await;
    let (ipc_client, _event_rx) = ipc::IpcClient::connect(sock_path.to_str().unwrap())
        .await
        .expect("Connect to test IPC socket");
    (
        api::state::ApiState::new(Arc::new(ipc_client), test_security()),
        requests,
    )
}

/// Create a test ApiState using a real temporary TCP loopback socket.
#[cfg(not(unix))]
async fn test_state() -> api::state::ApiState {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    // Spawn a dummy server that accepts but never responds.
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

    let (ipc_client, _event_rx) = ipc::IpcClient::connect(&addr.to_string())
        .await
        .expect("Connect to test IPC socket");

    api::state::ApiState::new(Arc::new(ipc_client), test_security())
}

#[cfg(not(unix))]
async fn test_state_with_runtime_ready_response(result: Value) -> api::state::ApiState {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    tokio::spawn(async move {
        loop {
            if let Ok((stream, _)) = listener.accept().await {
                let result = result.clone();
                tokio::spawn(async move {
                    let (reader, mut writer) = stream.into_split();
                    let mut lines = BufReader::new(reader).lines();
                    while let Ok(Some(line)) = lines.next_line().await {
                        let request: Value = serde_json::from_str(&line).unwrap();
                        assert_eq!(request["method"], "runtime.ready");
                        let response = serde_json::json!({
                            "id": request["id"],
                            "result": result,
                        });
                        writer
                            .write_all(format!("{}\n", response).as_bytes())
                            .await
                            .unwrap();
                        writer.flush().await.unwrap();
                    }
                });
            }
        }
    });

    tokio::task::yield_now().await;

    let (ipc_client, _event_rx) = ipc::IpcClient::connect(&addr.to_string())
        .await
        .expect("Connect to test IPC socket");

    api::state::ApiState::new(Arc::new(ipc_client), test_security())
}

#[cfg(not(unix))]
async fn test_state_with_api_forward_response(
    result: Value,
) -> (api::state::ApiState, Arc<Mutex<Vec<Value>>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let requests = Arc::new(Mutex::new(Vec::new()));
    let observed = Arc::clone(&requests);
    tokio::spawn(async move {
        loop {
            if let Ok((stream, _)) = listener.accept().await {
                let result = result.clone();
                let observed = Arc::clone(&observed);
                tokio::spawn(async move {
                    let (reader, mut writer) = stream.into_split();
                    let mut lines = BufReader::new(reader).lines();
                    while let Ok(Some(line)) = lines.next_line().await {
                        let request: Value = serde_json::from_str(&line).unwrap();
                        observed.lock().unwrap().push(request.clone());
                        let response = serde_json::json!({
                            "id": request["id"],
                            "result": result,
                        });
                        writer
                            .write_all(format!("{}\n", response).as_bytes())
                            .await
                            .unwrap();
                        writer.flush().await.unwrap();
                    }
                });
            }
        }
    });

    tokio::task::yield_now().await;
    let (ipc_client, _event_rx) = ipc::IpcClient::connect(&addr.to_string())
        .await
        .expect("Connect to test IPC socket");
    (
        api::state::ApiState::new(Arc::new(ipc_client), test_security()),
        requests,
    )
}

#[tokio::test]
async fn health_returns_ok() {
    let guard = router_test_guard();
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
    drop(guard);
}

#[tokio::test]
async fn business_routes_require_the_desktop_session_token() {
    let guard = router_test_guard();
    let (state, forwarded_requests) = test_state_with_api_forward_response(serde_json::json!({
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": {"unexpected": true}
    }))
    .await;
    let router = api::build_router(state);

    for request in [
        Request::builder()
            .uri("/api/ready")
            .body(Body::empty())
            .unwrap(),
        Request::builder()
            .uri("/api/plugins")
            .header(api::security::SESSION_TOKEN_HEADER, "wrong-token")
            .body(Body::empty())
            .unwrap(),
    ] {
        let response = router.clone().oneshot(request).await.unwrap();
        assert_eq!(response.status(), 401);
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let json: Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["error_code"], "desktop_auth_required");
    }

    assert!(forwarded_requests.lock().unwrap().is_empty());
    drop(guard);
}

#[tokio::test]
async fn unknown_proxy_paths_are_authenticated_before_ipc_forwarding() {
    let guard = router_test_guard();
    let (state, forwarded_requests) = test_state_with_api_forward_response(serde_json::json!({
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": {"forwarded": true}
    }))
    .await;
    let router = api::build_router(state);

    for request in [
        Request::builder()
            .uri("/api/unknown-private-route")
            .body(Body::empty())
            .unwrap(),
        Request::builder()
            .uri("/api/unknown-private-route")
            .header(api::security::SESSION_TOKEN_HEADER, "wrong-token")
            .body(Body::empty())
            .unwrap(),
    ] {
        let response = router.clone().oneshot(request).await.unwrap();
        assert_eq!(response.status(), 401);
    }
    assert!(forwarded_requests.lock().unwrap().is_empty());

    let response = router
        .oneshot(
            Request::builder()
                .uri("/api/unknown-private-route")
                .header(api::security::SESSION_TOKEN_HEADER, TEST_SESSION_TOKEN)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let requests = forwarded_requests.lock().unwrap();
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0]["params"]["path"], "/api/unknown-private-route");
    assert!(requests[0]["params"]["headers"]
        .get(api::security::SESSION_TOKEN_HEADER)
        .is_none());
    drop(guard);
}

#[tokio::test]
async fn unexpected_browser_origin_is_rejected_before_routing() {
    let guard = router_test_guard();
    let (state, forwarded_requests) = test_state_with_api_forward_response(serde_json::json!({
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": {"unexpected": true}
    }))
    .await;
    let router = api::build_router(state);
    let request = Request::builder()
        .uri("/api/plugins")
        .header(api::security::SESSION_TOKEN_HEADER, TEST_SESSION_TOKEN)
        .header("origin", "https://attacker.example")
        .body(Body::empty())
        .unwrap();

    let response = router.oneshot(request).await.unwrap();
    assert_eq!(response.status(), 403);
    assert!(response
        .headers()
        .get("access-control-allow-origin")
        .is_none());
    assert!(forwarded_requests.lock().unwrap().is_empty());
    drop(guard);
}

#[tokio::test]
async fn ready_returns_json() {
    let guard = router_test_guard();
    let state = test_state().await;
    let router = api::build_router(state);

    let req = Request::builder()
        .uri("/api/ready")
        .header(api::security::SESSION_TOKEN_HEADER, TEST_SESSION_TOKEN)
        .body(Body::empty())
        .unwrap();

    let response = router.oneshot(req).await.unwrap();

    assert_eq!(response.status(), 200);

    let body = response.into_body().collect().await.unwrap().to_bytes();
    let json: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(json["success"], true);
    assert!(json["data"]["ready"].is_boolean());
    assert!(json["data"]["startup_state"].is_string());
    drop(guard);
}

#[tokio::test]
async fn ready_uses_runtime_ready_ipc_response() {
    let home = isolated_home("ready-ipc");
    let state = test_state_with_runtime_ready_response(serde_json::json!({
        "success": true,
        "message": "Backend startup state",
        "data": {
            "ready": true,
            "status": "ready",
            "runtime_ready": true,
            "worker_ready": true,
            "llm_ready": true,
            "agent_runtime_ready": true,
            "runtime_status": "ready",
            "startup_state": "ready",
            "deferred_reason": "ipc-test"
        }
    }))
    .await;
    let router = api::build_router(state);

    let req = Request::builder()
        .uri("/api/ready")
        .header(api::security::SESSION_TOKEN_HEADER, TEST_SESSION_TOKEN)
        .body(Body::empty())
        .unwrap();

    let response = router.oneshot(req).await.unwrap();

    assert_eq!(response.status(), 200);

    let body = response.into_body().collect().await.unwrap().to_bytes();
    let json: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(json["data"]["status"], "ready");
    assert_eq!(json["data"]["runtime_status"], "ready");
    assert_eq!(json["data"]["ready"], true);
    assert_eq!(json["data"]["deferred_reason"], "ipc-test");
    drop(home);
}

#[tokio::test]
async fn ready_reports_unresponsive_when_ipc_does_not_reply() {
    let home = isolated_home("ready-timeout");
    let state = test_state().await;
    let router = api::build_router(state);

    let req = Request::builder()
        .uri("/api/ready")
        .header(api::security::SESSION_TOKEN_HEADER, TEST_SESSION_TOKEN)
        .body(Body::empty())
        .unwrap();

    let response = router.oneshot(req).await.unwrap();

    assert_eq!(response.status(), 200);

    let body = response.into_body().collect().await.unwrap().to_bytes();
    let json: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(json["data"]["status"], "degraded");
    assert_eq!(json["data"]["runtime_status"], "unresponsive");
    assert_eq!(json["data"]["ready"], false);
    drop(home);
}

#[tokio::test]
async fn runtime_overview_uses_worker_status_without_heartbeat_age() {
    let home = isolated_home("runtime-overview-worker-status");
    let state = test_state_with_runtime_ready_response(serde_json::json!({
        "success": true,
        "message": "Backend startup state",
        "data": {
            "ready": true,
            "status": "ready",
            "runtime_ready": true,
            "worker_ready": true,
            "llm_ready": true,
            "agent_runtime_ready": true,
            "runtime_status": "ready",
            "startup_state": "ready",
            "deferred_reason": null,
            "queue_backlog_healthy": true,
            "pending_commands": 2
        }
    }))
    .await;
    let router = api::build_router(state);

    let (status, json) = request_json(router, "GET", "/api/metrics/runtime/overview", None).await;

    assert_eq!(status, 200);
    let runtime = &json["data"]["runtime"];
    assert_eq!(runtime["status"], "ready");
    assert_eq!(runtime["runtime_status"], "ready");
    assert_eq!(runtime["pending_commands"], 2);
    assert!(runtime.get("runtime_heartbeat_age_ms").is_none());
    drop(home);
}

#[tokio::test]
async fn unknown_api_path_hits_fallback_proxy() {
    let guard = router_test_guard();
    let state = test_state().await;
    let router = api::build_router(state);

    let req = Request::builder()
        .uri("/api/nonexistent")
        .header(api::security::SESSION_TOKEN_HEADER, TEST_SESSION_TOKEN)
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
    drop(guard);
}

#[tokio::test]
async fn memory_l2_entities_searches_catalog_and_aliases() {
    let home = isolated_home("memory-l2-entities-search");
    let memory_dir = home.path().join(".magi").join("data").join("memory");
    std::fs::create_dir_all(&memory_dir).unwrap();
    let conn = rusqlite::Connection::open(memory_dir.join("memory.db")).unwrap();
    conn.execute_batch(
        r#"
        CREATE TABLE entity_catalog (
            entity_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            embedding_status TEXT NOT NULL DEFAULT 'disabled',
            last_embedded_at REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE entity_aliases (
            alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            alias_text TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        INSERT INTO entity_catalog(entity_id, canonical_name, entity_type, created_at, updated_at)
        VALUES
            ('hardware:iphone', 'Apple iPhone', 'hardware', 1, 1),
            ('product:melvor-idle', 'Melvor Idle', 'product', 2, 2),
            ('media:melvor-idle', 'Melvor Idle', 'media', 3, 3);
        INSERT INTO entity_aliases(entity_id, alias_text, normalized_alias, created_at, updated_at)
        VALUES
            ('product:melvor-idle', '梅尔沃放置', '梅尔沃放置', 2, 2),
            ('media:melvor-idle', '梅尔沃放置', '梅尔沃放置', 3, 3);
        "#,
    )
    .unwrap();
    drop(conn);

    let state = test_state().await;
    let router = api::build_router(state);

    let (status, json) = request_json(
        router,
        "GET",
        "/api/memory/l2/entities?limit=20&offset=0&query=%E6%A2%85%E5%B0%94",
        None,
    )
    .await;

    assert_eq!(status, 200);
    assert_eq!(json["total"], 2);
    let ids: Vec<&str> = json["items"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|item| item["entity_id"].as_str())
        .collect();
    assert_eq!(ids, vec!["media:melvor-idle", "product:melvor-idle"]);
    assert!(json["items"].to_string().contains("梅尔沃放置"));
    drop(home);
}

#[tokio::test]
async fn memory_object_routes_apply_search_query_in_native_gateway() {
    let home = isolated_home("memory-object-routes-search");
    let memory_dir = home.path().join(".magi").join("data").join("memory");
    std::fs::create_dir_all(&memory_dir).unwrap();
    let conn = rusqlite::Connection::open(memory_dir.join("memory.db")).unwrap();
    conn.execute_batch(
        r#"
        CREATE TABLE knowledge_graph (
            triple_id TEXT PRIMARY KEY,
            subject_id TEXT,
            subject_type TEXT,
            predicate TEXT,
            object_id TEXT,
            object_type TEXT,
            fact_kind TEXT,
            evidence_event_ids TEXT,
            evidence_text TEXT,
            natural_summary TEXT,
            source_type TEXT,
            extraction_method TEXT,
            evidence_class TEXT,
            status TEXT,
            updated_at REAL
        );
        CREATE TABLE tom_trait_assertions (
            assertion_id TEXT PRIMARY KEY,
            entity_id TEXT,
            entity_type TEXT,
            trait_family TEXT,
            trait_name TEXT,
            trait_value TEXT,
            evidence_events TEXT,
            source_domain TEXT,
            inference_depth TEXT,
            validation_state TEXT,
            target_entity_id TEXT,
            target_entity_type TEXT,
            target_scope TEXT,
            temporal_scope TEXT,
            context_ref_id TEXT,
            status TEXT,
            superseded_by TEXT,
            memory_subdomain TEXT,
            natural_summary TEXT,
            updated_at REAL
        );
        CREATE TABLE tom_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            entity_id TEXT,
            entity_type TEXT,
            core_traits TEXT,
            sensitive_triggers TEXT,
            preferences TEXT,
            public_sentiment_profile TEXT,
            relationship_topology TEXT,
            current_stress_level REAL,
            current_mood TEXT,
            current_engagement REAL,
            current_context TEXT,
            interaction_count INTEGER,
            last_interaction_at REAL,
            last_updated_at REAL,
            snapshot_version INTEGER,
            created_at REAL,
            update_source_assertion_ids TEXT,
            core_traits_history TEXT,
            preferences_history TEXT,
            relationship_history TEXT,
            active_record_ids TEXT,
            superseded_record_ids TEXT,
            emerging_signals TEXT,
            mood_trajectory TEXT
        );
        CREATE TABLE summaries (
            summary_id TEXT PRIMARY KEY,
            summary_type TEXT,
            summary_category TEXT,
            period_start REAL,
            period_end REAL,
            content TEXT,
            key_topics TEXT,
            key_entities TEXT,
            sentiment_summary TEXT,
            change_and_pattern TEXT,
            source_event_ids TEXT,
            source_event_count INTEGER,
            importance_aggregate REAL,
            generated_by_model TEXT,
            generation_prompt TEXT,
            generation_reason TEXT,
            insight_key TEXT,
            review_state TEXT,
            insight_metadata TEXT,
            narrative_style TEXT,
            essence_prose TEXT,
            created_at REAL,
            updated_at REAL
        );
        CREATE TABLE procedural_skills (
            skill_id TEXT PRIMARY KEY,
            skill_name TEXT,
            skill_category TEXT,
            skill_type TEXT,
            success_rate REAL,
            total_attempts INTEGER,
            circuit_breaker_state TEXT,
            optimized_prompt TEXT,
            optimized_params TEXT,
            context_affinity TEXT,
            source_event_ids TEXT,
            updated_at REAL
        );

        INSERT INTO knowledge_graph VALUES
            ('rel-apple', 'user:self', 'user', 'OWNS', 'hardware:iphone', 'hardware', 'fact', '[]', 'Apple phone', '', '', '', '', 'active', 1),
            ('rel-melvor', 'user:self', 'user', 'PLAYS', 'product:melvor-idle', 'product', 'fact', '[]', '梅尔沃放置', '', '', '', '', 'active', 2);
        INSERT INTO tom_trait_assertions VALUES
            ('assert-apple', 'user:self', 'user', 'preference', 'tool', 'iPhone', '[]', 'chat', 'explicit', 'stable', '', '', 'global', 'session', '', 'active', '', 'state', '', 1),
            ('assert-melvor', 'user:self', 'user', 'preference', 'game', '梅尔沃放置', '[]', 'chat', 'explicit', 'stable', '', '', 'global', 'session', '', 'active', '', 'state', '', 2);
        INSERT INTO tom_snapshots VALUES
            ('snap-apple', 'hardware:iphone', 'hardware', '{}', '', '{}', '', '{}', 0, 'neutral', 0, 'Apple context', 1, 1, 1, 1, 1, '[]', '', '', '', '', '', '', ''),
            ('snap-melvor', 'product:melvor-idle', 'product', '{"name":"梅尔沃放置"}', '', '{}', '', '{}', 0, 'neutral', 0, 'game context', 1, 1, 2, 1, 2, '[]', '', '', '', '', '', '', '');
        INSERT INTO summaries VALUES
            ('sum-apple', 'thematic', 'topic', 1, 1, 'Apple summary', '[]', '[]', '', '', '[]', 1, 0, 'model', '', '', '', 'ready', '{}', 'default', '', 1, 1),
            ('sum-melvor', 'thematic', 'topic', 2, 2, '梅尔沃放置 summary', '[]', '[]', '', '', '[]', 1, 0, 'model', '', '', '', 'ready', '{}', 'default', '', 2, 2);
        INSERT INTO procedural_skills VALUES
            ('skill-apple', 'Apple tool', 'tool', 'tool', 1.0, 1, 'closed', '', '', '', '[]', 1),
            ('skill-melvor', '梅尔沃 helper', 'tool', 'tool', 1.0, 1, 'closed', '', '', '', '[]', 2);
        "#,
    )
    .unwrap();
    drop(conn);

    let state = test_state().await;
    let router = api::build_router(state);
    let endpoints = [
        (
            "/api/memory/l2/relations?limit=20&offset=0&query=%E6%A2%85%E5%B0%94",
            "rel-melvor",
        ),
        (
            "/api/memory/l2/assertions?limit=20&offset=0&query=%E6%A2%85%E5%B0%94",
            "assert-melvor",
        ),
        (
            "/api/memory/l2/snapshots?limit=20&offset=0&query=%E6%A2%85%E5%B0%94",
            "snap-melvor",
        ),
        (
            "/api/memory/l3/summaries?limit=20&offset=0&query=%E6%A2%85%E5%B0%94",
            "sum-melvor",
        ),
        (
            "/api/memory/procedures?limit=20&offset=0&query=%E6%A2%85%E5%B0%94",
            "skill-melvor",
        ),
    ];

    for (endpoint, expected_id) in endpoints {
        let (status, json) = request_json(router.clone(), "GET", endpoint, None).await;
        assert_eq!(status, 200, "{endpoint}");
        assert_eq!(json["total"], 1, "{endpoint}");
        assert!(
            json["items"].to_string().contains(expected_id),
            "{endpoint} returned {json}"
        );
    }
    drop(home);
}

#[tokio::test]
async fn cors_allows_desktop_origin_and_session_header() {
    let guard = router_test_guard();
    let state = test_state().await;
    let router = api::build_router(state);

    let req = Request::builder()
        .method("OPTIONS")
        .uri("/api/health")
        .header("Origin", "http://127.0.0.1:5173")
        .header("Access-Control-Request-Method", "GET")
        .header(
            "Access-Control-Request-Headers",
            format!("{}, range", api::security::SESSION_TOKEN_HEADER),
        )
        .body(Body::empty())
        .unwrap();

    let response = router.oneshot(req).await.unwrap();

    assert!(
        response
            .headers()
            .contains_key("access-control-allow-origin"),
        "CORS allow-origin header should be present"
    );
    let allowed_headers = response
        .headers()
        .get("access-control-allow-headers")
        .and_then(|value| value.to_str().ok())
        .unwrap_or_default()
        .to_ascii_lowercase();
    assert!(allowed_headers.contains(api::security::SESSION_TOKEN_HEADER));
    assert!(allowed_headers.contains("range"));
    drop(guard);
}

#[tokio::test]
async fn cors_does_not_allow_untrusted_origins() {
    let guard = router_test_guard();
    let state = test_state().await;
    let router = api::build_router(state);
    let request = Request::builder()
        .method("OPTIONS")
        .uri("/api/tasks")
        .header("origin", "https://attacker.example")
        .header("access-control-request-method", "GET")
        .header(
            "access-control-request-headers",
            api::security::SESSION_TOKEN_HEADER,
        )
        .body(Body::empty())
        .unwrap();

    let response = router.oneshot(request).await.unwrap();
    assert!(response
        .headers()
        .get("access-control-allow-origin")
        .is_none());
    drop(guard);
}

#[tokio::test]
async fn builtin_avatars_are_public_and_user_avatars_require_authentication() {
    let guard = router_test_guard();
    let base = std::env::temp_dir().join(format!(
        "magi-avatar-access-test-{}-{}",
        std::process::id(),
        TEST_COUNTER.fetch_add(1, Ordering::SeqCst)
    ));
    let builtin_dir = base.join("builtin");
    let user_dir = base.join("user");
    std::fs::create_dir_all(&builtin_dir).unwrap();
    std::fs::create_dir_all(&user_dir).unwrap();
    std::fs::write(builtin_dir.join("builtin.png"), b"builtin").unwrap();
    std::fs::write(user_dir.join("private.png"), b"private").unwrap();

    let state = test_state()
        .await
        .with_avatar_dirs(Some(builtin_dir), Some(user_dir));
    let router = api::build_router(state);

    let public = router
        .clone()
        .oneshot(
            Request::builder()
                .uri("/static/avatars/builtin.png")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(public.status(), 200);
    let public_body = public.into_body().collect().await.unwrap().to_bytes();
    assert_eq!(public_body.as_ref(), b"builtin");

    let unauthenticated = router
        .clone()
        .oneshot(
            Request::builder()
                .uri("/static/user-avatars/private.png")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(unauthenticated.status(), 401);

    let authenticated = router
        .oneshot(
            Request::builder()
                .uri("/static/user-avatars/private.png")
                .header(api::security::SESSION_TOKEN_HEADER, TEST_SESSION_TOKEN)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(authenticated.status(), 200);
    let authenticated_body = authenticated
        .into_body()
        .collect()
        .await
        .unwrap()
        .to_bytes();
    assert_eq!(authenticated_body.as_ref(), b"private");

    let _ = std::fs::remove_dir_all(base);
    drop(guard);
}

#[tokio::test]
async fn private_resource_ticket_is_scoped_and_reusable() {
    let home = isolated_home("private-resource-ticket");
    let avatar_dir = home.path().join("avatars");
    std::fs::create_dir_all(&avatar_dir).unwrap();
    std::fs::write(avatar_dir.join("private.png"), b"private-avatar").unwrap();
    std::fs::write(avatar_dir.join("other.png"), b"other-avatar").unwrap();

    let mut state = test_state().await;
    state.user_avatar_dir = Some(avatar_dir);
    let router = api::build_router(state);
    let (status, grant) = request_json(
        router.clone(),
        "POST",
        "/api/private-resource-tickets",
        Some(r#"{"kind":"user_avatar","filename":"private.png"}"#),
    )
    .await;
    assert_eq!(status, 201);
    let access_url = grant["data"]["access_url"].as_str().unwrap();

    let direct = router
        .clone()
        .oneshot(
            Request::builder()
                .uri("/static/user-avatars/private.png")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(direct.status(), 401);

    let wrong_method = router
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(access_url)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(wrong_method.status(), 401);

    for _ in 0..2 {
        let response = router
            .clone()
            .oneshot(
                Request::builder()
                    .uri(access_url)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), 200);
        assert_eq!(
            response.headers().get("cache-control").unwrap(),
            "private, no-store"
        );
        assert_eq!(
            response.headers().get("referrer-policy").unwrap(),
            "no-referrer"
        );
        assert_eq!(
            response.headers().get("x-content-type-options").unwrap(),
            "nosniff"
        );
        assert_eq!(
            response.headers().get("content-security-policy").unwrap(),
            "sandbox; default-src 'none'"
        );
        let body = response.into_body().collect().await.unwrap().to_bytes();
        assert_eq!(body.as_ref(), b"private-avatar");
    }

    let head = router
        .clone()
        .oneshot(
            Request::builder()
                .method("HEAD")
                .uri(access_url)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(head.status(), 200);
    assert!(head
        .into_body()
        .collect()
        .await
        .unwrap()
        .to_bytes()
        .is_empty());

    let range = router
        .clone()
        .oneshot(
            Request::builder()
                .uri(access_url)
                .header("range", "bytes=0-6")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(range.status(), 206);
    assert_eq!(
        range.headers().get("content-range").unwrap(),
        "bytes 0-6/14"
    );
    let range_body = range.into_body().collect().await.unwrap().to_bytes();
    assert_eq!(range_body.as_ref(), b"private");

    let ticket_query = access_url.split_once('?').unwrap().1;
    let unexpected_query = router
        .clone()
        .oneshot(
            Request::builder()
                .uri(format!("{access_url}&unexpected=1"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(unexpected_query.status(), 401);

    let wrong_resource = router
        .oneshot(
            Request::builder()
                .uri(format!("/static/user-avatars/other.png?{ticket_query}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(wrong_resource.status(), 401);
    drop(home);
}

#[tokio::test]
async fn expired_private_resource_ticket_is_rejected() {
    let home = isolated_home("expired-private-resource-ticket");
    let avatar_dir = home.path().join("avatars");
    std::fs::create_dir_all(&avatar_dir).unwrap();
    std::fs::write(avatar_dir.join("private.png"), b"private-avatar").unwrap();

    let mut state = test_state().await;
    state.user_avatar_dir = Some(avatar_dir);
    state.security = Arc::new(api::security::GatewaySecurity::with_policy(
        TEST_SESSION_TOKEN,
        ["http://127.0.0.1:5173"],
        std::time::Duration::from_millis(10),
        8,
    ));
    let router = api::build_router(state);
    let (status, grant) = request_json(
        router.clone(),
        "POST",
        "/api/private-resource-tickets",
        Some(r#"{"kind":"user_avatar","filename":"private.png"}"#),
    )
    .await;
    assert_eq!(status, 201);
    let access_url = grant["data"]["access_url"].as_str().unwrap();

    tokio::time::sleep(std::time::Duration::from_millis(30)).await;
    let response = router
        .oneshot(
            Request::builder()
                .uri(access_url)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), 401);
    drop(home);
}

#[tokio::test]
async fn timeline_resource_ticket_is_removed_before_python_forwarding() {
    let guard = router_test_guard();
    let (state, forwarded_requests) = test_state_with_api_forward_response(serde_json::json!({
        "status": 200,
        "headers": {"content-type": "image/png"},
        "body_encoding": "base64",
        "body_base64": "cG5n"
    }))
    .await;
    let router = api::build_router(state);
    let (status, grant) = request_json(
        router.clone(),
        "POST",
        "/api/private-resource-tickets",
        Some(r#"{"kind":"timeline_asset","asset_ref":"photo-library://day/image.png"}"#),
    )
    .await;
    assert_eq!(status, 201);
    let access_url = grant["data"]["access_url"].as_str().unwrap();

    let response = router
        .oneshot(
            Request::builder()
                .uri(access_url)
                .header("range", "bytes=0-2")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let body = response.into_body().collect().await.unwrap().to_bytes();
    assert_eq!(body.as_ref(), b"png");

    let requests = forwarded_requests.lock().unwrap();
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0]["params"]["query"], "");
    assert_eq!(requests[0]["params"]["headers"]["range"], "bytes=0-2");
    assert!(requests[0]["params"]["headers"]
        .get(api::security::SESSION_TOKEN_HEADER)
        .is_none());
    drop(guard);
}

#[tokio::test]
async fn chat_attachment_ticket_binds_user_and_supports_head() {
    let home = isolated_home("chat-attachment-ticket");
    let magi_root = home.path().join(".magi");
    let chat_dir = magi_root.join("data").join("chat");
    let attachment_dir = magi_root
        .join("data")
        .join("resources")
        .join("chat")
        .join("images")
        .join("session-1")
        .join("turn-1");
    std::fs::create_dir_all(&chat_dir).unwrap();
    std::fs::create_dir_all(&attachment_dir).unwrap();
    let attachment_path = attachment_dir.join("att-1__photo.png");
    std::fs::write(&attachment_path, b"private-attachment").unwrap();

    let conn = rusqlite::Connection::open(chat_dir.join("chat.db")).unwrap();
    conn.execute_batch(
        "CREATE TABLE chat_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            deleted_at_ms INTEGER
        );
        CREATE TABLE chat_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            is_visible INTEGER NOT NULL
        );
        CREATE TABLE chat_attachments (
            attachment_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            original_name TEXT NOT NULL,
            storage_rel_path TEXT NOT NULL
        );
        INSERT INTO chat_sessions (session_id, user_id, deleted_at_ms)
        VALUES ('session-1', 'local_user', NULL);
        INSERT INTO chat_messages (
            message_id, session_id, turn_id, user_id, is_visible
        ) VALUES ('msg-1', 'session-1', 'turn-1', 'local_user', 1);
        INSERT INTO chat_attachments (
            attachment_id, session_id, turn_id, message_id, user_id,
            kind, mime_type, original_name, storage_rel_path
        ) VALUES (
            'att-1', 'session-1', 'turn-1', 'msg-1', 'local_user',
            'image', 'image/png', 'photo.png',
            'data/resources/chat/images/session-1/turn-1/att-1__photo.png'
        );",
    )
    .unwrap();
    drop(conn);

    let state = test_state().await;
    let router = api::build_router(state);
    let (status, grant) = request_json(
        router.clone(),
        "POST",
        "/api/private-resource-tickets",
        Some(
            r#"{
                "kind":"chat_attachment",
                "user_id":"local_user",
                "session_id":"session-1",
                "attachment_id":"att-1"
            }"#,
        ),
    )
    .await;
    assert_eq!(status, 201);
    let access_url = grant["data"]["access_url"].as_str().unwrap();
    assert!(access_url.contains("user_id=local_user"));

    let response = router
        .clone()
        .oneshot(
            Request::builder()
                .uri(access_url)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(
        response.headers().get("cache-control").unwrap(),
        "private, no-store"
    );
    let body = response.into_body().collect().await.unwrap().to_bytes();
    assert_eq!(body.as_ref(), b"private-attachment");

    let head = router
        .clone()
        .oneshot(
            Request::builder()
                .method("HEAD")
                .uri(access_url)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(head.status(), 200);
    assert!(head
        .into_body()
        .collect()
        .await
        .unwrap()
        .to_bytes()
        .is_empty());

    let range = router
        .clone()
        .oneshot(
            Request::builder()
                .uri(access_url)
                .header("range", "bytes=0-6")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(range.status(), 206);
    assert_eq!(
        range.headers().get("content-range").unwrap(),
        "bytes 0-6/18"
    );
    let body = range.into_body().collect().await.unwrap().to_bytes();
    assert_eq!(body.as_ref(), b"private");

    let wrong_user_url = access_url.replace("user_id=local_user", "user_id=other_user");
    let wrong_user = router
        .oneshot(
            Request::builder()
                .uri(wrong_user_url)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(wrong_user.status(), 401);
    drop(home);
}

#[tokio::test]
async fn native_read_routes_return_stable_empty_payloads_when_databases_are_missing() {
    let home = isolated_home("missing-dbs");
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
    drop(home);
}

#[tokio::test]
async fn attachment_upload_route_forwards_multipart_to_python() {
    let home = isolated_home("upload-attachment");
    let forwarded_body = serde_json::json!({
        "success": true,
        "message": "Attachment uploaded",
        "data": {
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "attachment": {
                "attachment_id": "attachment-1",
                "kind": "text_file",
                "parse_status": "pending"
            }
        }
    });
    let (state, requests) = test_state_with_api_forward_response(serde_json::json!({
        "status": 201,
        "headers": {
            "content-type": "application/json",
            "x-magi-upload-owner": "python"
        },
        "body": forwarded_body
    }))
    .await;
    let router = api::build_router(state);

    let boundary = "magi-boundary";
    let body = format!(
        "--{boundary}\r\nContent-Disposition: form-data; name=\"user_id\"\r\n\r\nlocal_user\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"turn_id\"\r\n\r\nturn-1\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"notes.txt\"\r\nContent-Type: text/plain\r\n\r\nhello rust native upload\r\n--{boundary}--\r\n"
    );

    let req = Request::builder()
        .method("POST")
        .uri("/api/messages/session/session-1/attachments")
        .header(api::security::SESSION_TOKEN_HEADER, TEST_SESSION_TOKEN)
        .header("origin", "http://127.0.0.1:5173")
        .header(
            "content-type",
            format!("multipart/form-data; boundary={boundary}"),
        )
        .body(Body::from(body))
        .unwrap();

    let response = router.oneshot(req).await.unwrap();
    assert_eq!(response.status(), 201);
    assert_eq!(
        response.headers().get("x-magi-upload-owner").unwrap(),
        "python"
    );
    assert!(response
        .headers()
        .contains_key("access-control-allow-origin"));

    let body = response.into_body().collect().await.unwrap().to_bytes();
    let json: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(json["success"], true);
    assert_eq!(json["data"]["attachment"]["kind"], "text_file");
    assert_eq!(json["data"]["attachment"]["parse_status"], "pending");

    let observed = requests.lock().unwrap();
    let request = observed.first().expect("forwarded IPC request");
    assert_eq!(request["method"], "api.forward");
    assert_eq!(request["params"]["method"], "POST");
    assert_eq!(
        request["params"]["path"],
        "/api/messages/session/session-1/attachments"
    );
    assert!(request["params"]["headers"]["content-type"]
        .as_str()
        .unwrap()
        .contains("multipart/form-data"));
    assert!(request["params"]["headers"]
        .get(api::security::SESSION_TOKEN_HEADER)
        .is_none());
    let staged_path = request["params"]["body_file_path"]
        .as_str()
        .expect("staged multipart path");
    assert!(!Path::new(staged_path).exists());
    assert!(!home
        .path()
        .join(".magi/data/resources/chat/files/session-1")
        .exists());
}

#[tokio::test]
async fn attachment_upload_proxy_accepts_large_body_and_cleans_on_failure() {
    let home = isolated_home("upload-attachment-large");
    let (state, requests) = test_state_with_api_forward_response(serde_json::json!({
        "status": 400,
        "headers": {
            "content-type": "application/json"
        },
        "body": {
            "detail": "Rejected by Python attachment validation"
        }
    }))
    .await;
    let router = api::build_router(state);
    let boundary = "magi-large-boundary";
    let header = format!(
        "--{boundary}\r\nContent-Disposition: form-data; name=\"turn_id\"\r\n\r\nturn-1\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"large.txt\"\r\nContent-Type: text/plain\r\n\r\n"
    )
    .into_bytes();
    let footer = format!("\r\n--{boundary}--\r\n").into_bytes();
    let chunks = std::iter::once(Ok::<_, std::convert::Infallible>(axum::body::Bytes::from(
        header,
    )))
    .chain((0..11).map(|_| Ok(axum::body::Bytes::from(vec![b'x'; 1024 * 1024]))))
    .chain(std::iter::once(Ok(axum::body::Bytes::from(footer))));
    let req = Request::builder()
        .method("POST")
        .uri("/api/messages/session/session-1/attachments")
        .header(api::security::SESSION_TOKEN_HEADER, TEST_SESSION_TOKEN)
        .header(
            "content-type",
            format!("multipart/form-data; boundary={boundary}"),
        )
        .body(Body::from_stream(futures_util::stream::iter(chunks)))
        .unwrap();

    let response = router.oneshot(req).await.unwrap();
    assert_eq!(response.status(), 400);
    let response_body = response.into_body().collect().await.unwrap().to_bytes();
    let json: Value = serde_json::from_slice(&response_body).unwrap();
    assert_eq!(json["detail"], "Rejected by Python attachment validation");

    let observed = requests.lock().unwrap();
    let request = observed.first().expect("forwarded IPC request");
    let staged_path = request["params"]["body_file_path"]
        .as_str()
        .expect("staged multipart path");
    assert!(!Path::new(staged_path).exists());
    drop(observed);
    drop(home);
}

#[tokio::test]
async fn attachment_upload_proxy_rejects_stream_over_limit_without_ipc_or_temp_leak() {
    let home = isolated_home("upload-attachment-over-limit");
    let (state, requests) = test_state_with_api_forward_response(serde_json::json!({
        "status": 201,
        "headers": {"content-type": "application/json"},
        "body": {"unexpected": true}
    }))
    .await;
    let router = api::build_router(state);
    let temp_before = staged_ipc_body_paths();
    let chunks = (0..56).map(|_| {
        Ok::<_, std::convert::Infallible>(axum::body::Bytes::from(vec![b'x'; 1024 * 1024]))
    });
    let req = Request::builder()
        .method("POST")
        .uri("/api/messages/session/session-1/attachments")
        .header(api::security::SESSION_TOKEN_HEADER, TEST_SESSION_TOKEN)
        .header("content-type", "multipart/form-data; boundary=over-limit")
        .body(Body::from_stream(futures_util::stream::iter(chunks)))
        .unwrap();

    let response = router.oneshot(req).await.unwrap();

    assert_eq!(response.status(), 400);
    assert!(requests.lock().unwrap().is_empty());
    assert_eq!(staged_ipc_body_paths(), temp_before);
    drop(home);
}

#[tokio::test]
async fn native_session_creation_uses_server_identity_and_deduplicates_retries() {
    let home = isolated_home("session-creation-idempotency");
    let chat_dir = home.path().join(".magi").join("data").join("chat");
    std::fs::create_dir_all(&chat_dir).unwrap();
    let conn = rusqlite::Connection::open(chat_dir.join("chat.db")).unwrap();
    conn.execute_batch(
        "CREATE TABLE chat_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            title_overridden INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            last_message_at_ms INTEGER,
            last_user_message_at_ms INTEGER,
            last_message_preview TEXT NOT NULL DEFAULT '',
            last_user_message_preview TEXT NOT NULL DEFAULT '',
            message_count INTEGER NOT NULL DEFAULT 0,
            workspace_path TEXT,
            history_version INTEGER NOT NULL DEFAULT 0,
            archived_at_ms INTEGER,
            deleted_at_ms INTEGER
        );
        CREATE TABLE chat_session_creation_requests (
            user_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            session_id TEXT NOT NULL UNIQUE,
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY (user_id, idempotency_key)
        );",
    )
    .unwrap();
    drop(conn);

    let state = test_state().await;
    let router = api::build_router(state);
    let uri = "/api/messages/session/new?user_id=u1&idempotency_key=first_context_request_1";
    let (first_status, first) = request_json(router.clone(), "POST", uri, None).await;
    let (retry_status, retry) = request_json(router.clone(), "POST", uri, None).await;

    assert_eq!(first_status, 201, "first={first:?} home={:?}", home.path());
    assert_eq!(retry_status, 201, "retry={retry:?} home={:?}", home.path());
    assert_eq!(first["session_id"], retry["session_id"]);
    assert!(first["session_id"]
        .as_str()
        .is_some_and(|value| value.starts_with("session_")));
    assert_ne!(first["session_id"], "first_context_request_1");

    let (other_user_status, other_user) = request_json(
        router.clone(),
        "POST",
        "/api/messages/session/new?user_id=u2&idempotency_key=first_context_request_1",
        None,
    )
    .await;
    assert_eq!(other_user_status, 201, "other_user={other_user:?}");
    assert_ne!(first["session_id"], other_user["session_id"]);

    let (invalid_status, invalid) = request_json(
        router,
        "POST",
        "/api/messages/session/new?user_id=u1&idempotency_key=contains%20space",
        None,
    )
    .await;
    assert_eq!(invalid_status, 400, "invalid={invalid:?}");

    let conn = rusqlite::Connection::open(chat_dir.join("chat.db")).unwrap();
    let session_count: i64 = conn
        .query_row("SELECT COUNT(*) FROM chat_sessions", [], |row| row.get(0))
        .unwrap();
    let request_count: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM chat_session_creation_requests",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(session_count, 2);
    assert_eq!(request_count, 2);
    drop(home);
}

#[tokio::test]
async fn native_message_routes_return_history_versions() {
    let home = isolated_home("message-history-version");
    let chat_dir = home.path().join(".magi").join("data").join("chat");
    std::fs::create_dir_all(&chat_dir).unwrap();
    let conn = rusqlite::Connection::open(chat_dir.join("chat.db")).unwrap();
    conn.execute_batch(
        "CREATE TABLE chat_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            title_overridden INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            last_message_at_ms INTEGER,
            last_user_message_at_ms INTEGER,
            last_message_preview TEXT NOT NULL DEFAULT '',
            last_user_message_preview TEXT NOT NULL DEFAULT '',
            message_count INTEGER NOT NULL DEFAULT 0,
            history_version INTEGER NOT NULL DEFAULT 0,
            workspace_path TEXT,
            archived_at_ms INTEGER,
            deleted_at_ms INTEGER
        );
        CREATE TABLE chat_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            turn_id TEXT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            message_kind TEXT NOT NULL,
            content_text TEXT,
            payload_json TEXT,
            is_final INTEGER NOT NULL DEFAULT 1,
            is_visible INTEGER NOT NULL DEFAULT 1,
            created_at_ms INTEGER NOT NULL,
            sequence_no INTEGER NOT NULL DEFAULT 0,
            replaces_message_id TEXT,
            replaced_by_message_id TEXT,
            persona_id TEXT,
            reply_to_message_id TEXT,
            label_json TEXT
        );
        INSERT INTO chat_sessions (
            session_id, user_id, title, title_overridden, summary, created_at_ms, updated_at_ms,
            last_message_at_ms, last_user_message_at_ms, last_message_preview,
            last_user_message_preview, message_count, history_version, workspace_path,
            archived_at_ms, deleted_at_ms
        ) VALUES (
            's-history', 'u1', 'History Session', 0, '', 1000, 2000,
            2000, 1000, 'assistant preview', 'hello', 1, 7, NULL, NULL, NULL
        );
        INSERT INTO chat_messages (
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible, created_at_ms, sequence_no,
            replaces_message_id, replaced_by_message_id, persona_id, reply_to_message_id, label_json
        ) VALUES (
            'msg-1', 's-history', 'turn-1', 'u1', 'user', 'user_text',
            'hello', '{}', 1, 1, 1000, 1, NULL, NULL, 'persona-1', NULL, NULL
        );",
    )
    .unwrap();
    drop(conn);

    let state = test_state().await;
    let router = api::build_router(state);

    let (status, history) = request_json(
        router.clone(),
        "GET",
        "/api/messages/history?user_id=u1&session_id=s-history",
        None,
    )
    .await;
    assert_eq!(status, 200, "history={history:?} home={:?}", home.path());
    assert_eq!(history["history_version"], 7);
    assert_eq!(history["count"], 1);
    assert_eq!(history["messages"][0]["content"], "hello");
    assert_eq!(history["messages"][0]["persona_id"], "persona-1");

    let (status, sessions) =
        request_json(router, "GET", "/api/messages/sessions?user_id=u1", None).await;
    assert_eq!(status, 200, "sessions={sessions:?} home={:?}", home.path());
    assert_eq!(sessions["sessions"][0]["history_version"], 7);
    drop(home);
}

#[tokio::test]
async fn delete_session_route_is_governed_by_python_runtime() {
    let home = isolated_home("delete-session");
    let magi_root = home.path().join(".magi");
    let chat_dir = magi_root.join("data").join("chat");
    let memory_dir = magi_root.join("data").join("memory");
    let runtime_dir = magi_root.join("runtime");
    std::fs::create_dir_all(&chat_dir).unwrap();
    std::fs::create_dir_all(&memory_dir).unwrap();
    std::fs::create_dir_all(&runtime_dir).unwrap();

    let conn = rusqlite::Connection::open(chat_dir.join("chat.db")).unwrap();
    conn.execute_batch(
        "CREATE TABLE chat_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            title_overridden INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            last_message_at_ms INTEGER,
            last_user_message_at_ms INTEGER,
            last_message_preview TEXT NOT NULL DEFAULT '',
            last_user_message_preview TEXT NOT NULL DEFAULT '',
            message_count INTEGER NOT NULL DEFAULT 0,
            history_version INTEGER NOT NULL DEFAULT 0,
            workspace_path TEXT,
            archived_at_ms INTEGER,
            deleted_at_ms INTEGER
        );
        CREATE TABLE chat_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            turn_id TEXT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            message_kind TEXT NOT NULL,
            content_text TEXT,
            payload_json TEXT,
            is_final INTEGER NOT NULL DEFAULT 1,
            is_visible INTEGER NOT NULL DEFAULT 1,
            created_at_ms INTEGER NOT NULL,
            sequence_no INTEGER NOT NULL DEFAULT 0,
            replaces_message_id TEXT,
            replaced_by_message_id TEXT,
            persona_id TEXT,
            reply_to_message_id TEXT,
            label_json TEXT
        );
        CREATE TABLE chat_attachments (
            attachment_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            message_id TEXT,
            user_id TEXT NOT NULL,
            mime_type TEXT,
            original_name TEXT,
            storage_rel_path TEXT
        );
        CREATE TABLE chat_turns (
            turn_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            ux_plan_json TEXT
        );
        INSERT INTO chat_sessions (
            session_id, user_id, title, title_overridden, summary, created_at_ms, updated_at_ms,
            last_message_at_ms, last_user_message_at_ms, last_message_preview,
            last_user_message_preview, message_count, history_version, workspace_path,
            archived_at_ms, deleted_at_ms
        ) VALUES (
            's-delete', 'u1', 'Delete Me', 0, '', 1000, 2000,
            2000, 1000, 'bye', 'hello', 1, 4, NULL, NULL, NULL
        );
        INSERT INTO chat_messages (
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible, created_at_ms, sequence_no,
            replaces_message_id, replaced_by_message_id, persona_id, reply_to_message_id, label_json
        ) VALUES (
            'msg-delete', 's-delete', 'turn-delete', 'u1', 'user', 'user_text',
            'hello', '{}', 1, 1, 1000, 1, NULL, NULL, NULL, NULL, NULL
        );
        INSERT INTO chat_attachments (
            attachment_id, session_id, message_id, user_id, mime_type, original_name, storage_rel_path
        ) VALUES (
            'att-delete', 's-delete', 'msg-delete', 'u1', 'text/plain', 'note.txt', 'attachments/note.txt'
        );
        INSERT INTO chat_turns (turn_id, session_id, user_id, ux_plan_json) VALUES (
            'turn-delete', 's-delete', 'u1', '{}'
        );",
    )
    .unwrap();
    drop(conn);

    let l1_conn = rusqlite::Connection::open(memory_dir.join("l1_events.db")).unwrap();
    l1_conn
        .execute_batch(
            "CREATE TABLE fact_events (
                id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT,
                deleted_at INTEGER
            );
            INSERT INTO fact_events (id, user_id, session_id, deleted_at)
            VALUES (1, 'u1', 's-delete', NULL);",
        )
        .unwrap();
    drop(l1_conn);

    let trace_conn = rusqlite::Connection::open(runtime_dir.join("runtime_trace.db")).unwrap();
    trace_conn
        .execute_batch(
            "CREATE TABLE trace_turns (
                trace_id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL
            );
            CREATE TABLE trace_spans (
                span_id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL
            );
            CREATE TABLE trace_llm_calls (
                call_id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL
            );
            CREATE TABLE trace_tools (
                tool_call_id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL
            );
            CREATE TABLE trace_intent_resolutions (
                resolution_id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL
            );
            INSERT INTO trace_turns (trace_id, turn_id, session_id, user_id)
            VALUES ('trace-1', 'turn-delete', 's-delete', 'u1');
            INSERT INTO trace_spans (span_id, turn_id) VALUES ('span-1', 'turn-delete');
            INSERT INTO trace_llm_calls (call_id, turn_id) VALUES ('llm-1', 'turn-delete');
            INSERT INTO trace_tools (tool_call_id, turn_id) VALUES ('tool-1', 'turn-delete');
            INSERT INTO trace_intent_resolutions (resolution_id, turn_id)
            VALUES ('intent-1', 'turn-delete');",
        )
        .unwrap();
    drop(trace_conn);

    let (state, forwarded_requests) = test_state_with_api_forward_response(serde_json::json!({
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": {
            "success": true,
            "user_id": "u1",
            "deleted_session_id": "s-delete"
        }
    }))
    .await;
    let router = api::build_router(state);
    let (status, response) = request_json(
        router.clone(),
        "DELETE",
        "/api/messages/session/s-delete?user_id=u1",
        None,
    )
    .await;

    assert_eq!(status, 200, "response={response:?} home={:?}", home.path());
    assert_eq!(response["success"], true);
    assert_eq!(response["deleted_session_id"], "s-delete");
    let requests = forwarded_requests.lock().unwrap();
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0]["method"], "api.forward");
    assert_eq!(requests[0]["params"]["method"], "DELETE");
    assert_eq!(
        requests[0]["params"]["path"],
        "/api/messages/session/s-delete"
    );
    assert_eq!(requests[0]["params"]["query"], "user_id=u1");
    drop(requests);

    let conn = rusqlite::Connection::open(chat_dir.join("chat.db")).unwrap();
    let deleted_at_ms: Option<i64> = conn
        .query_row(
            "SELECT deleted_at_ms FROM chat_sessions WHERE session_id = 's-delete'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let history_version: i64 = conn
        .query_row(
            "SELECT history_version FROM chat_sessions WHERE session_id = 's-delete'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let message_count: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM chat_messages WHERE session_id = 's-delete'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let attachment_count: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM chat_attachments WHERE session_id = 's-delete'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let turn_count: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM chat_turns WHERE session_id = 's-delete'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    drop(conn);

    assert!(deleted_at_ms.is_none());
    assert_eq!(history_version, 4);
    assert_eq!(message_count, 1);
    assert_eq!(attachment_count, 1);
    assert_eq!(turn_count, 1);

    let l1_conn = rusqlite::Connection::open(memory_dir.join("l1_events.db")).unwrap();
    let l1_count: i64 = l1_conn
        .query_row(
            "SELECT COUNT(*) FROM fact_events WHERE session_id = 's-delete'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    drop(l1_conn);
    assert_eq!(l1_count, 1);

    let trace_conn = rusqlite::Connection::open(runtime_dir.join("runtime_trace.db")).unwrap();
    let trace_turn_count: i64 = trace_conn
        .query_row(
            "SELECT COUNT(*) FROM trace_turns WHERE session_id = 's-delete'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let trace_span_count: i64 = trace_conn
        .query_row("SELECT COUNT(*) FROM trace_spans", [], |row| row.get(0))
        .unwrap();
    let trace_llm_count: i64 = trace_conn
        .query_row("SELECT COUNT(*) FROM trace_llm_calls", [], |row| row.get(0))
        .unwrap();
    let trace_tool_count: i64 = trace_conn
        .query_row("SELECT COUNT(*) FROM trace_tools", [], |row| row.get(0))
        .unwrap();
    let trace_intent_count: i64 = trace_conn
        .query_row("SELECT COUNT(*) FROM trace_intent_resolutions", [], |row| {
            row.get(0)
        })
        .unwrap();
    drop(trace_conn);

    assert_eq!(trace_turn_count, 1);
    assert_eq!(trace_span_count, 1);
    assert_eq!(trace_llm_count, 1);
    assert_eq!(trace_tool_count, 1);
    assert_eq!(trace_intent_count, 1);

    let (status, sessions) =
        request_json(router, "GET", "/api/messages/sessions?user_id=u1", None).await;
    assert_eq!(status, 200, "sessions={sessions:?} home={:?}", home.path());
    assert_eq!(sessions["count"], 1);
    assert_eq!(sessions["sessions"].as_array().unwrap().len(), 1);
    drop(home);
}

#[tokio::test]
async fn delete_message_route_is_governed_by_python_runtime() {
    let guard = router_test_guard();
    let (state, forwarded_requests) = test_state_with_api_forward_response(serde_json::json!({
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": {
            "success": true,
            "user_id": "u1",
            "session_id": "s1",
            "deleted_message_id": "m1"
        }
    }))
    .await;
    let router = api::build_router(state);

    let (status, response) = request_json(
        router,
        "DELETE",
        "/api/messages/session/s1/message/m1?user_id=u1",
        None,
    )
    .await;

    assert_eq!(status, 200);
    assert_eq!(response["deleted_message_id"], "m1");
    let requests = forwarded_requests.lock().unwrap();
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0]["method"], "api.forward");
    assert_eq!(requests[0]["params"]["method"], "DELETE");
    assert_eq!(
        requests[0]["params"]["path"],
        "/api/messages/session/s1/message/m1"
    );
    assert_eq!(requests[0]["params"]["query"], "user_id=u1");
    drop(guard);
}

#[tokio::test]
async fn assertion_confirmation_is_governed_by_python_runtime() {
    let guard = router_test_guard();
    let (state, forwarded_requests) = test_state_with_api_forward_response(serde_json::json!({
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": {"assertion_id": "assert-1"}
    }))
    .await;
    let router = api::build_router(state);

    let (feedback_status, feedback_response) = request_json(
        router.clone(),
        "PATCH",
        "/api/memory/l2/assertions/assert-1/feedback",
        Some(r#"{"feedback":"confirmed"}"#),
    )
    .await;
    assert_eq!(feedback_status, 200);
    assert_eq!(feedback_response["assertion_id"], "assert-1");

    let requests = forwarded_requests.lock().unwrap();
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0]["method"], "api.forward");
    assert_eq!(requests[0]["params"]["method"], "PATCH");
    assert_eq!(
        requests[0]["params"]["path"],
        "/api/memory/l2/assertions/assert-1/feedback"
    );
    assert_eq!(
        requests[0]["params"]["body"],
        serde_json::json!({"feedback": "confirmed"})
    );
    drop(guard);
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

    assert_eq!(status, 201, "created={created:?} home={:?}", home.path());
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
    assert_eq!(
        status,
        200,
        "created={created:?} fetched={fetched:?} home={:?}",
        home.path()
    );
    assert_eq!(fetched["task"]["task_id"], task_id);
    assert_eq!(fetched["task"]["user_id"], "u1");
    drop(home);
}
