use super::state::ApiState;
use axum::{
    extract::{Query, State},
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Challenge {
    nonce: Option<String>,
}

/// Credential-free liveness can prove the paired identity without disclosing business data.
pub async fn health(State(state): State<ApiState>, Query(challenge): Query<Challenge>) -> Response {
    let payload = match challenge.nonce {
        None => json!({"status": "ok"}),
        Some(nonce) => match state.security.auth.route_proof(&nonce) {
            Ok(proof) => serde_json::to_value(proof).expect("serialize route proof"),
            Err(_) => {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(json!({"error": "Invalid route challenge"})),
                )
                    .into_response()
            }
        },
    };
    ([(header::CACHE_CONTROL, "no-store")], Json(payload)).into_response()
}
