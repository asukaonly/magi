//! Epoch admission stays inside the gateway maintenance permit, including IPC completion.

use super::{proxy, security::AuthenticatedClient, state::ApiState};
use axum::{
    body::{to_bytes, Body},
    extract::{Request, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use magi_service_contract::delivery::{DeliveryBatch, MAX_BATCH_BYTES};

pub async fn receive(State(state): State<ApiState>, request: Request) -> Response {
    let Ok(_slot) = state.background_deliveries.clone().try_acquire_owned() else {
        return (
            StatusCode::TOO_MANY_REQUESTS,
            [("retry-after", "5")],
            "Background delivery is busy",
        )
            .into_response();
    };
    let (parts, body) = request.into_parts();
    let Ok(bytes) = to_bytes(body, MAX_BATCH_BYTES).await else {
        return (
            StatusCode::PAYLOAD_TOO_LARGE,
            "Background batch exceeds size limit",
        )
            .into_response();
    };
    let Ok(batch) = serde_json::from_slice::<DeliveryBatch>(&bytes) else {
        return (StatusCode::UNPROCESSABLE_ENTITY, "Invalid background batch").into_response();
    };
    if batch.validate().is_err() {
        return (StatusCode::UNPROCESSABLE_ENTITY, "Invalid background batch").into_response();
    }
    if let Some(client) = parts.extensions.get::<AuthenticatedClient>() {
        if let Some(scope) = state.security.auth.collector_scope(&client.client_id) {
            let allowed = batch.events.iter().all(|event| matches!(&event.payload,
                magi_service_contract::delivery::BackgroundPayload::PluginEvent { connection_id, event_type, data, .. }
                if connection_id == &scope.connection_id && event_type == "source.change.v1" && data.get("source_type").and_then(|v|v.as_str()) == Some(&scope.source_type)));
            if !allowed {
                return (
                    StatusCode::FORBIDDEN,
                    "Collector event exceeds its source grant",
                )
                    .into_response();
            }
        }
    }
    let Some(maintenance) = state.maintenance.as_ref() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    if batch.server_id != state.security.auth.server_id
        || batch.data_epoch != maintenance.status().data_epoch
    {
        return (StatusCode::CONFLICT, "Background delivery scope changed").into_response();
    }
    proxy::proxy_handler(State(state), Request::from_parts(parts, Body::from(bytes)))
        .await
        .into_response()
}
