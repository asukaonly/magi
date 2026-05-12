use axum::{
    body::Body,
    extract::{Request, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use base64::Engine;
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

use super::state::ApiState;

const MAX_PROXY_BODY_BYTES: usize = 10 * 1024 * 1024;
const BODY_FILE_PREFIX: &str = "magi-ipc-body-";

pub async fn proxy_handler(State(state): State<ApiState>, req: Request) -> impl IntoResponse {
    ipc_proxy(&state.ipc_client, req).await
}

async fn ipc_proxy(ipc: &crate::ipc::IpcClient, req: Request) -> Response {
    let method = req.method().to_string();
    let path = req.uri().path().to_string();
    let query = req.uri().query().unwrap_or("").to_string();

    // Collect headers
    let mut headers = serde_json::Map::new();
    for (name, value) in req.headers() {
        let name_lower = name.as_str().to_ascii_lowercase();
        if name_lower == "connection"
            || name_lower == "content-length"
            || name_lower == "transfer-encoding"
        {
            continue;
        }
        if let Ok(v) = value.to_str() {
            headers.insert(name.to_string(), Value::String(v.to_string()));
        }
    }

    // Read body
    let body_bytes = match axum::body::to_bytes(req.into_body(), MAX_PROXY_BODY_BYTES).await {
        Ok(b) => b,
        Err(_) => return (StatusCode::BAD_REQUEST, "Request body too large").into_response(),
    };

    let (params, staged_body_path) =
        match build_ipc_params(method, path, query, headers, &body_bytes) {
            Ok(value) => value,
            Err(_) => {
                return (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "Failed to stage request body for IPC forwarding",
                )
                    .into_response();
            }
        };

    let response = match ipc.request("api.forward", Some(params)).await {
        Ok(result) => build_response_from_ipc(result),
        Err(e) => (StatusCode::BAD_GATEWAY, format!("IPC error: {e}")).into_response(),
    };

    if let Some(path) = staged_body_path {
        let _ = fs::remove_file(path);
    }

    response
}

fn build_ipc_params(
    method: String,
    path: String,
    query: String,
    headers: serde_json::Map<String, Value>,
    body_bytes: &[u8],
) -> std::io::Result<(Value, Option<PathBuf>)> {
    let mut params = serde_json::Map::new();
    params.insert("method".to_string(), Value::String(method));
    params.insert("path".to_string(), Value::String(path));
    params.insert("query".to_string(), Value::String(query));
    params.insert("headers".to_string(), Value::Object(headers));

    if !body_bytes.is_empty() {
        if let Ok(json_body) = serde_json::from_slice::<Value>(body_bytes) {
            params.insert("body".to_string(), json_body);
        } else {
            let staged_path = stage_request_body(body_bytes)?;
            params.insert(
                "body_file_path".to_string(),
                Value::String(staged_path.to_string_lossy().into_owned()),
            );
            return Ok((Value::Object(params), Some(staged_path)));
        }
    }

    Ok((Value::Object(params), None))
}

fn stage_request_body(body_bytes: &[u8]) -> std::io::Result<PathBuf> {
    let path = std::env::temp_dir().join(format!("{BODY_FILE_PREFIX}{}", uuid::Uuid::new_v4()));
    fs::write(&path, body_bytes)?;
    Ok(path)
}

fn build_response_from_ipc(result: Value) -> Response {
    let status = result.get("status").and_then(|s| s.as_u64()).unwrap_or(200) as u16;

    let status_code = StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);

    let body_bytes = match result.get("body_encoding").and_then(|s| s.as_str()) {
        Some("base64") => result
            .get("body_base64")
            .and_then(|value| value.as_str())
            .and_then(|payload| {
                base64::engine::general_purpose::STANDARD
                    .decode(payload)
                    .ok()
            })
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

    builder.body(Body::from(body_bytes)).unwrap_or_else(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, "Response build error").into_response()
    })
}

#[cfg(test)]
mod tests {
    use super::{build_ipc_params, build_response_from_ipc};
    use axum::http::StatusCode;
    use http_body_util::BodyExt;
    use serde_json::json;

    #[test]
    fn stages_binary_request_body_in_temp_file() {
        let (params, staged_path) = build_ipc_params(
            "POST".to_string(),
            "/api/upload".to_string(),
            "".to_string(),
            serde_json::Map::new(),
            b"\x89PNG\r\n",
        )
        .expect("build proxy params");

        let staged_path = staged_path.expect("staged file path");
        assert_eq!(
            params
                .get("body_file_path")
                .and_then(|value| value.as_str()),
            Some(staged_path.to_string_lossy().as_ref())
        );
        assert_eq!(std::fs::read(&staged_path).unwrap(), b"\x89PNG\r\n");
        assert!(params.get("body").is_none());

        std::fs::remove_file(staged_path).unwrap();
    }

    #[test]
    fn keeps_json_request_body_structured() {
        let (params, staged_path) = build_ipc_params(
            "POST".to_string(),
            "/api/echo".to_string(),
            "".to_string(),
            serde_json::Map::new(),
            br#"{"ok":true}"#,
        )
        .expect("build proxy params");

        assert_eq!(params.get("body"), Some(&json!({"ok": true})));
        assert!(params.get("body_file_path").is_none());
        assert!(staged_path.is_none());
    }

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
