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
async fn product_and_diagnostic_streams_have_independent_cursors_and_reset_together() {
    let security = Arc::new(GatewaySecurity::new("owner"));
    let state = ApiState::with_runtime(Arc::new(RuntimeConnection::default()), security);
    let hub = Arc::clone(&state.events);
    let product_cursor = hub.resync_hint("initial").envelope.event_id.clone();
    let diagnostic_cursor = hub.diagnostics().resync_hint("initial").envelope.event_id.clone();
    let payload = magi_gateway::notification_bridge::NotificationPayload {
        channel: "trace_update".into(), user_id: "local_user".into(), session_id: "s".into(),
        turn_id: Some("t".into()), data: json!({"session_id":"s","turn_id":"t","trace_summary":{"private":true}}),
    };
    hub.publish_notification("execution_trace_update", &payload);
    assert!(hub.subscribe(Some(&product_cursor)).unwrap().replay.is_empty());
    assert_eq!(hub.diagnostics().subscribe(Some(&diagnostic_cursor)).unwrap().replay.len(), 1);
    let router = api::build_router(state);
    for (scope, cursor, expected) in [("product", &diagnostic_cursor, "resync_required"), ("diagnostics", &diagnostic_cursor, "execution_trace_update")] {
        let response = router.clone().oneshot(Request::builder()
            .uri(format!("/api/events?scope={scope}"))
            .header("x-magi-session-token", "owner")
            .header("last-event-id", cursor).body(Body::empty()).unwrap()).await.unwrap();
        assert_eq!(response.status(), 200);
        let mut stream = response.into_body().into_data_stream();
        let first = tokio::time::timeout(Duration::from_secs(1), stream.next()).await.unwrap().unwrap().unwrap();
        assert!(std::str::from_utf8(&first).unwrap().contains(expected));
    }
    hub.reset("content_cleared");
    let replay = hub.diagnostics().subscribe(Some(&diagnostic_cursor)).unwrap().replay;
    assert_eq!(replay.len(), 1);
    assert_eq!(replay[0].envelope.event_type, "resync_required");
}

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
