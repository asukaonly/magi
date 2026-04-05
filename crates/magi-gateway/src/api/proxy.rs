use axum::{
    body::Body,
    extract::{Request, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use serde_json::Value;

use super::state::ApiState;

pub async fn proxy_handler(
    State(state): State<ApiState>,
    req: Request,
) -> impl IntoResponse {
    ipc_proxy(&state.ipc_client, req).await
}

async fn ipc_proxy(
    ipc: &crate::ipc::IpcClient,
    req: Request,
) -> Response {
    let method = req.method().to_string();
    let path = req.uri().path().to_string();
    let query = req.uri().query().unwrap_or("").to_string();

    // Collect headers
    let mut headers = serde_json::Map::new();
    for (name, value) in req.headers() {
        if let Ok(v) = value.to_str() {
            headers.insert(name.to_string(), Value::String(v.to_string()));
        }
    }

    // Read body
    let body_bytes = match axum::body::to_bytes(req.into_body(), 10 * 1024 * 1024).await {
        Ok(b) => b,
        Err(_) => return (StatusCode::BAD_REQUEST, "Request body too large").into_response(),
    };

    let body: Option<Value> = if body_bytes.is_empty() {
        None
    } else {
        serde_json::from_slice(&body_bytes).ok().or_else(|| {
            Some(Value::String(
                String::from_utf8_lossy(&body_bytes).to_string(),
            ))
        })
    };

    let params = serde_json::json!({
        "method": method,
        "path": path,
        "query": query,
        "headers": headers,
        "body": body,
    });

    match ipc.request("api.forward", Some(params)).await {
        Ok(result) => build_response_from_ipc(result),
        Err(e) => {
            (StatusCode::BAD_GATEWAY, format!("IPC error: {e}")).into_response()
        }
    }
}

fn build_response_from_ipc(result: Value) -> Response {
    let status = result
        .get("status")
        .and_then(|s| s.as_u64())
        .unwrap_or(200) as u16;

    let status_code = StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);

    let body = result.get("body").cloned().unwrap_or(Value::Null);
    let body_str = serde_json::to_string(&body).unwrap_or_default();

    let mut builder = Response::builder().status(status_code);

    // Forward content-type header if present
    if let Some(headers) = result.get("headers").and_then(|h| h.as_object()) {
        for (key, val) in headers {
            if let Some(v) = val.as_str() {
                let key_lower = key.to_lowercase();
                // Skip hop-by-hop headers
                if key_lower == "transfer-encoding" || key_lower == "connection" {
                    continue;
                }
                if let Ok(name) = axum::http::header::HeaderName::from_bytes(key.as_bytes()) {
                    builder = builder.header(name, v);
                }
            }
        }
    }

    builder
        .body(Body::from(body_str))
        .unwrap_or_else(|_| (StatusCode::INTERNAL_SERVER_ERROR, "Response build error").into_response())
}
