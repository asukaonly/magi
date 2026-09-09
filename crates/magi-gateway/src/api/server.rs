use std::sync::{atomic::Ordering, Arc};

use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Extension, Json,
};
use serde::{Deserialize, Serialize};

use super::{security::PairingCredential, state::ApiState};
use crate::auth::{AccessSession, AuthStore};

pub async fn info(State(state): State<ApiState>) -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "success": true,
        "data": {
            "server_id": state.security.auth.server_id,
            "protocol_version": magi_service_contract::SERVER_PROTOCOL_VERSION,
            "events": state.events.status(),
            "maintenance": state.maintenance.as_ref().map(|control| control.status()),
            "service_ready": state.storage_ready.load(Ordering::Acquire),
            "supervisor": state.supervisor.read().unwrap_or_else(|error| error.into_inner()).clone(),
            "plugin_execution": "server",
        }
    }))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PairRequest {
    name: String,
}

pub async fn pair(
    State(state): State<ApiState>,
    Extension(grant): Extension<PairingCredential>,
    Json(payload): Json<PairRequest>,
) -> Response {
    operation(state, move |auth| auth.pair(&grant.0, &payload.name)).await
}

pub async fn session(Extension(session): Extension<AccessSession>) -> Json<serde_json::Value> {
    Json(serde_json::json!({ "success": true, "data": session }))
}

pub async fn create_pairing(State(state): State<ApiState>) -> Response {
    operation(state, |auth| auth.create_pairing_grant()).await
}

pub async fn clients(State(state): State<ApiState>) -> Response {
    operation(state, |auth| auth.clients()).await
}

pub async fn revoke(State(state): State<ApiState>, Path(client_id): Path<String>) -> Response {
    operation(state, move |auth| auth.revoke(&client_id)).await
}

async fn operation<T, F>(state: ApiState, operation: F) -> Response
where
    T: Serialize + Send + 'static,
    F: FnOnce(&AuthStore) -> Result<T, String> + Send + 'static,
{
    let Ok(permit) = Arc::clone(&state.security.auth_operations).try_acquire_owned() else {
        return failure(StatusCode::TOO_MANY_REQUESTS, "auth_busy");
    };
    let auth = Arc::clone(&state.security.auth);
    match tokio::task::spawn_blocking(move || {
        let _permit = permit;
        operation(&auth)
    })
    .await
    {
        Ok(Ok(data)) => Json(serde_json::json!({ "success": true, "data": data })).into_response(),
        Ok(Err(_)) => failure(StatusCode::BAD_REQUEST, "auth_operation_rejected"),
        Err(_) => failure(StatusCode::INTERNAL_SERVER_ERROR, "auth_operation_failed"),
    }
}

fn failure(status: StatusCode, code: &str) -> Response {
    (status, Json(serde_json::json!({
        "success": false, "error_code": code, "message": "Authentication operation could not be completed"
    }))).into_response()
}
