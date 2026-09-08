use std::sync::Arc;
use std::time::Duration;

use axum::{body::Body, http::Request};
use futures_util::StreamExt;
use magi_gateway::{
    api::{self, security::GatewaySecurity, state::ApiState},
    ipc::RuntimeConnection,
};
use serde_json::json;
use tower::ServiceExt;

#[tokio::test]
async fn event_stream_replays_and_stops_after_device_revocation() {
    let security = Arc::new(GatewaySecurity::new("owner"));
    let grant = security.auth.create_pairing_grant().unwrap();
    let client = security
        .auth
        .pair(&grant.pairing_token, "Subscriber")
        .unwrap();
    let access = security.auth.renew(&client.client_credential).unwrap();
    let state = ApiState::with_runtime(
        Arc::new(RuntimeConnection::default()),
        Arc::clone(&security),
    );
    let hub = Arc::clone(&state.events);
    let initial = hub.resync_hint("initial");
    hub.publish("state.changed", json!({"resource":"tasks"}));
    let router = api::build_router(state);
    let unauthorized = router
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/events")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(unauthorized.status(), 401);
    let response = router
        .oneshot(
            Request::builder()
                .uri("/api/events")
                .header("x-magi-session-token", &access.access_token)
                .header("last-event-id", &initial.envelope.event_id)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(response.headers()["content-type"], "text/event-stream");
    assert_eq!(response.headers()["cache-control"], "private, no-store");
    let mut stream = response.into_body().into_data_stream();
    let first = tokio::time::timeout(Duration::from_secs(1), stream.next())
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    let text = std::str::from_utf8(&first).unwrap();
    assert!(text.contains("state.changed"));
    assert!(text.contains("tasks"));
    security.auth.revoke(&client.client_id).unwrap();
    hub.publish(
        "runtime.notification",
        json!({"private":"after revocation"}),
    );
    assert!(tokio::time::timeout(Duration::from_secs(3), stream.next())
        .await
        .unwrap()
        .is_none());
}
