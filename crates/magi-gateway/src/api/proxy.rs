use axum::{
    body::Body,
    extract::{Request, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use base64::Engine;
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

    let body_bytes = match result.get("body_encoding").and_then(|s| s.as_str()) {
        Some("base64") => result
            .get("body_base64")
            .and_then(|value| value.as_str())
            .and_then(|payload| base64::engine::general_purpose::STANDARD.decode(payload).ok())
            .unwrap_or_default(),
        _ => match result.get("body") {
            Some(Value::String(text)) => text.as_bytes().to_vec(),
            Some(Value::Null) | None => Vec::new(),
            Some(other) => serde_json::to_vec(other).unwrap_or_default(),
        },
    };

    let mut builder = Response::builder().status(status_code);

    // Forward content-type header if present
    if let Some(headers) = result.get("headers").and_then(|h| h.as_object()) {
        for (key, val) in headers {
            if let Some(v) = val.as_str() {
                let key_lower = key.to_lowercase();
                // Skip hop-by-hop and length headers — hyper computes
                // content-length from the actual body we send.
                if key_lower == "transfer-encoding"
                    || key_lower == "connection"
                    || key_lower == "content-length"
                {
                    continue;
                }
                if let Ok(name) = axum::http::header::HeaderName::from_bytes(key.as_bytes()) {
                    builder = builder.header(name, v);
                }
            }
        }
    }

    builder
        .body(Body::from(body_bytes))
        .unwrap_or_else(|_| (StatusCode::INTERNAL_SERVER_ERROR, "Response build error").into_response())
}

#[cfg(test)]
mod tests {
    use super::build_response_from_ipc;
    use axum::http::StatusCode;
    use http_body_util::BodyExt;
    use serde_json::json;

    #[tokio::test]
    async fn decodes_base64_binary_body() {
        let response = build_response_from_ipc(json!({
            "status": 200,
            "headers": {
                "content-type": "image/png",
                "content-disposition": "inline; filename=\"photo.png\""
            },
            "body_encoding": "base64",
            "body_base64": "iVBORw0K"
        }));

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.headers().get("content-type").unwrap(), "image/png");

        let body = response.into_body().collect().await.unwrap().to_bytes();
        assert_eq!(&body[..], b"\x89PNG\r\n");
    }
}
