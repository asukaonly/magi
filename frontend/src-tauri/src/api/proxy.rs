use axum::{
    body::Body,
    extract::{Request, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};

use super::state::ApiState;

pub async fn proxy_handler(
    State(state): State<ApiState>,
    req: Request,
) -> impl IntoResponse {
    let path_and_query = req
        .uri()
        .path_and_query()
        .map(|pq| pq.to_string())
        .unwrap_or_else(|| "/".to_string());

    let uri = format!(
        "http://127.0.0.1:{}{}",
        state.python_api_port, path_and_query
    )
    .parse::<hyper::Uri>();

    let uri = match uri {
        Ok(u) => u,
        Err(_) => return (StatusCode::BAD_REQUEST, "Invalid URI").into_response(),
    };

    let (mut parts, body) = req.into_parts();
    parts.uri = uri;
    parts.headers.remove("host");

    let proxy_req = Request::from_parts(parts, body);

    match state.client.request(proxy_req).await {
        Ok(resp) => {
            let (parts, body) = resp.into_parts();
            Response::from_parts(parts, Body::new(body))
        }
        Err(_) => (StatusCode::BAD_GATEWAY, "Backend unavailable").into_response(),
    }
}
