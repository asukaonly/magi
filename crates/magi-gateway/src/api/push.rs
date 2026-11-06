use super::{security::AuthenticatedClient, state::ApiState};
use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
    Extension, Json,
};
use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Registration {
    server_id: String,
    data_epoch: String,
    token: String,
    environment: String,
}

pub async fn status(
    State(state): State<ApiState>,
    Extension(client): Extension<AuthenticatedClient>,
) -> Response {
    match state.security.auth.push_devices() {
        Ok(devices) => Json(json!({"success":true,"data":{"available":state.apns.is_some(),
            "registered":devices.iter().any(|d|d.client_id==client.client_id && state.maintenance.as_ref().is_some_and(|c|c.status().data_epoch==d.data_epoch))}})).into_response(),
        Err(_) => StatusCode::SERVICE_UNAVAILABLE.into_response(),
    }
}

pub async fn register(
    State(state): State<ApiState>,
    Extension(client): Extension<AuthenticatedClient>,
    Json(body): Json<Registration>,
) -> Response {
    if state.apns.is_none() {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    }
    if body.server_id != state.security.auth.server_id
        || !state
            .maintenance
            .as_ref()
            .is_some_and(|c| c.status().data_epoch == body.data_epoch)
    {
        return StatusCode::CONFLICT.into_response();
    }
    let Ok(tail) = crate::push::feed(&state, None).await else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    let device = crate::auth::push::PushDevice {
        client_id: client.client_id,
        token: body.token.to_ascii_lowercase(),
        environment: body.environment,
        data_epoch: body.data_epoch,
        after_id: tail.next_id,
    };
    match state.security.auth.register_push(&device) {
        Ok(()) => Json(json!({"success":true,"data":{"available":true,"registered":true}}))
            .into_response(),
        Err(_) => StatusCode::BAD_REQUEST.into_response(),
    }
}

pub async fn remove(
    State(state): State<ApiState>,
    Extension(client): Extension<AuthenticatedClient>,
) -> Response {
    match state.security.auth.remove_push(&client.client_id) {
        Ok(()) => Json(
            json!({"success":true,"data":{"available":state.apns.is_some(),"registered":false}}),
        )
        .into_response(),
        Err(_) => StatusCode::SERVICE_UNAVAILABLE.into_response(),
    }
}
