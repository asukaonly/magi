use super::state::ApiState;
use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    Json,
};

pub async fn status(State(state): State<ApiState>) -> Response {
    let Some(control) = &state.maintenance else {
        return unavailable();
    };
    Json(serde_json::json!({"success":true,"data":control.status()})).into_response()
}

pub async fn clear(State(state): State<ApiState>, headers: HeaderMap) -> Response {
    let Some(control) = &state.maintenance else {
        return unavailable();
    };
    let Some(operation_id) = headers
        .get("x-magi-full-clear-transaction")
        .and_then(|value| value.to_str().ok())
    else {
        return (
            StatusCode::BAD_REQUEST,
            "A unique clear operation identifier is required",
        )
            .into_response();
    };
    match control.begin_clear(operation_id.to_owned()).await {
        Ok(status) => (StatusCode::ACCEPTED, Json(serde_json::json!({"success":true,"data":status}))).into_response(),
        Err(error) => (StatusCode::CONFLICT, Json(serde_json::json!({"success":false,"message":error,"error_code":"maintenance_conflict"}))).into_response(),
    }
}

fn unavailable() -> Response {
    (StatusCode::SERVICE_UNAVAILABLE, Json(serde_json::json!({"success":false,"error_code":"service_host_required","message":"Service lifecycle owner is unavailable"}))).into_response()
}

pub async fn operation(
    State(state): State<ApiState>,
    Path(operation_id): Path<String>,
) -> Response {
    let Some(control) = &state.maintenance else {
        return unavailable();
    };
    match control.operation_status(operation_id).await {
        Ok(Some(status)) => Json(serde_json::json!({"success":true,"data":status})).into_response(),
        Ok(None) => (StatusCode::NOT_FOUND, "Maintenance operation was not found").into_response(),
        Err(_) => (StatusCode::BAD_REQUEST, "Maintenance operation is invalid").into_response(),
    }
}

pub async fn restore(State(state): State<ApiState>, Path(candidate_id): Path<String>) -> Response {
    let Some(control) = &state.maintenance else {
        return unavailable();
    };
    match control.begin_restore(candidate_id).await {
        Ok(status) => (StatusCode::ACCEPTED, Json(serde_json::json!({"success":true,"data":status}))).into_response(),
        Err(error) => (StatusCode::CONFLICT, Json(serde_json::json!({"success":false,"message":error,"error_code":"maintenance_conflict"}))).into_response(),
    }
}

/// Control routes remain available while all content routes are drained.
pub fn is_control_path(path: &str) -> bool {
    matches!(
        path,
        "/api/events"
            | "/api/health"
            | "/api/ready"
            | "/api/server/maintenance"
            | "/api/memory/clear"
            | "/api/server/info"
            | "/api/auth/pair"
            | "/api/auth/session"
            | "/api/server/pairing-grants"
            | "/api/server/clients"
    ) || path.starts_with("/api/server/clients/")
        || path.starts_with("/api/server/maintenance/")
        || path.starts_with("/static/avatars/")
        || path
            .strip_prefix("/api/memory/portability/restores/")
            .and_then(|rest| rest.strip_suffix("/confirm"))
            .is_some_and(|id| !id.is_empty() && !id.contains('/'))
}
