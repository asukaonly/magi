use std::sync::{atomic::Ordering, Arc};

use axum::{body::Body, http::Request, Router};
use http_body_util::BodyExt;
use magi_gateway::{
    api::{self, security::GatewaySecurity, state::ApiState},
    ipc::RuntimeConnection,
};
use serde_json::{json, Value};
use tower::ServiceExt;

async fn request(
    router: &Router,
    method: &str,
    path: &str,
    token: &str,
    body: Value,
) -> (u16, Value) {
    let response = router
        .clone()
        .oneshot(
            Request::builder()
                .method(method)
                .uri(path)
                .header("x-magi-session-token", token)
                .header("content-type", "application/json")
                .body(Body::from(serde_json::to_vec(&body).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status().as_u16();
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

#[tokio::test]
async fn pairing_exchange_and_revocation_are_enforced_through_the_router() {
    let security = Arc::new(GatewaySecurity::new("owner"));
    let state = ApiState::with_runtime(Arc::new(RuntimeConnection::default()), security);
    let ready = Arc::clone(&state.storage_ready);
    let router = api::build_router(state);
    assert_eq!(
        request(&router, "GET", "/api/server/info", "", Value::Null)
            .await
            .0,
        401
    );
    let (status, grant) = request(
        &router,
        "POST",
        "/api/server/pairing-grants",
        "owner",
        Value::Null,
    )
    .await;
    assert_eq!(status, 200);
    let grant = grant["data"]["pairing_token"].as_str().unwrap();
    assert_eq!(
        request(&router, "GET", "/api/server/info", grant, Value::Null)
            .await
            .0,
        401
    );
    let (status, client) = request(
        &router,
        "POST",
        "/api/auth/pair",
        grant,
        json!({"name":"Laptop"}),
    )
    .await;
    assert_eq!(status, 200);
    assert_eq!(
        request(
            &router,
            "POST",
            "/api/auth/pair",
            grant,
            json!({"name":"Again"})
        )
        .await
        .0,
        401
    );
    let credential = client["data"]["client_credential"].as_str().unwrap();
    let id = client["data"]["client_id"].as_str().unwrap();
    assert_eq!(
        request(&router, "GET", "/api/server/info", credential, Value::Null)
            .await
            .0,
        401
    );
    let (status, session) = request(
        &router,
        "POST",
        "/api/auth/session",
        credential,
        Value::Null,
    )
    .await;
    assert_eq!(status, 200);
    let access = session["data"]["access_token"].as_str().unwrap();
    let (status, info) = request(&router, "GET", "/api/server/info", access, Value::Null).await;
    assert_eq!(status, 200);
    assert_eq!(info["data"]["service_ready"], false);
    assert_eq!(
        request(&router, "POST", "/api/auth/session", access, Value::Null)
            .await
            .0,
        401
    );
    ready.store(true, Ordering::Release);
    let (status, ticket) = request(
        &router,
        "POST",
        "/api/private-resource-tickets",
        access,
        json!({"kind":"user_avatar","filename":"test.png"}),
    )
    .await;
    assert_eq!(status, 201);
    let resource = ticket["data"]["access_url"].as_str().unwrap();
    assert_eq!(
        request(&router, "GET", resource, "", Value::Null).await.0,
        404
    );
    assert_eq!(
        request(
            &router,
            "DELETE",
            &format!("/api/server/clients/{id}"),
            "owner",
            Value::Null
        )
        .await
        .0,
        200
    );
    assert_eq!(
        request(&router, "GET", "/api/server/info", access, Value::Null)
            .await
            .0,
        401
    );
    assert_eq!(
        request(
            &router,
            "POST",
            "/api/auth/session",
            credential,
            Value::Null
        )
        .await
        .0,
        401
    );
    assert_eq!(
        request(&router, "GET", resource, "", Value::Null).await.0,
        401
    );
}
