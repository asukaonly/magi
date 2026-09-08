use super::state::ApiState;
use axum::{
    extract::State,
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
