use axum::{
    body::Body,
    extract::{Request, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use base64::Engine;
use http_body_util::BodyExt;
use serde_json::Value;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use tokio::io::AsyncWriteExt;

use super::state::ApiState;

const MAX_PROXY_BODY_BYTES: usize = 10 * 1024 * 1024;
const BODY_FILE_PREFIX: &str = "magi-ipc-body-";

/// RAII guard for a temp file staged for IPC body forwarding.
///
/// The file is deleted when this guard goes out of scope — including on
/// panic, early return, and axum future cancellation (browser tab closed,
/// client disconnected mid-request). When it owns an open streaming file,
/// the descriptor is dropped before deletion so cleanup also works on
/// Windows.
///
/// After staging succeeds, the guard stays alive until `ipc.request().await`
/// returns, so Python has already read the staged body before deletion.
/// Earlier exits clean up immediately.
struct StagedBodyGuard {
    path: Option<PathBuf>,
    streaming_file: Option<tokio::fs::File>,
}

impl StagedBodyGuard {
    fn new(path: Option<PathBuf>) -> Self {
        Self {
            path,
            streaming_file: None,
        }
    }

    fn with_streaming_file(path: PathBuf, file: tokio::fs::File) -> Self {
        Self {
            path: Some(path),
            streaming_file: Some(file),
        }
    }

    fn streaming_file_mut(&mut self) -> &mut tokio::fs::File {
        self.streaming_file
            .as_mut()
            .expect("streaming staged file must be available")
    }

    fn close_streaming_file(&mut self) {
        self.streaming_file.take();
    }

    fn disarm(&mut self) {
        self.close_streaming_file();
        self.path = None;
    }
}

impl Drop for StagedBodyGuard {
    fn drop(&mut self) {
        self.close_streaming_file();
        if let Some(path) = self.path.take() {
            let _ = std::fs::remove_file(path);
        }
    }
}

pub async fn proxy_handler(State(state): State<ApiState>, req: Request) -> impl IntoResponse {
    ipc_proxy(&state.ipc_client, req, MAX_PROXY_BODY_BYTES).await
}

pub async fn attachment_upload_proxy_handler(
    State(state): State<ApiState>,
    req: Request,
) -> impl IntoResponse {
    attachment_upload_ipc_proxy(
        &state.ipc_client,
        req,
        super::messages::MAX_ATTACHMENT_UPLOAD_BODY_BYTES,
    )
    .await
}

async fn attachment_upload_ipc_proxy(
    ipc: &crate::ipc::IpcClient,
    req: Request,
    max_body_bytes: usize,
) -> Response {
    let method = req.method().to_string();
    let path = req.uri().path().to_string();
    let query = req.uri().query().unwrap_or("").to_string();
    let headers = collect_forward_headers(req.headers());
    let staged_path = new_staged_body_path();
    let staged_file = match create_secure_staged_file(&staged_path) {
        Ok(file) => tokio::fs::File::from_std(file),
        Err(_) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Failed to stage request body for IPC forwarding",
            )
                .into_response();
        }
    };
    let mut staged_guard = StagedBodyGuard::with_streaming_file(staged_path.clone(), staged_file);

    match stream_body_to_file(
        req.into_body(),
        staged_guard.streaming_file_mut(),
        max_body_bytes,
    )
    .await
    {
        Ok(()) => {}
        Err(StageBodyError::TooLarge | StageBodyError::Read) => {
            return (StatusCode::BAD_REQUEST, "Request body too large or invalid").into_response();
        }
        Err(StageBodyError::Io) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Failed to stage request body for IPC forwarding",
            )
                .into_response();
        }
    }
    staged_guard.close_streaming_file();

    let params = build_staged_ipc_params(method, path, query, headers, &staged_path);
    let _staged_guard = staged_guard;
    match ipc.request("api.forward", Some(params)).await {
        Ok(result) => build_response_from_ipc(result),
        Err(e) => (StatusCode::BAD_GATEWAY, format!("IPC error: {e}")).into_response(),
    }
}

async fn ipc_proxy(ipc: &crate::ipc::IpcClient, req: Request, max_body_bytes: usize) -> Response {
    let method = req.method().to_string();
    let path = req.uri().path().to_string();
    let query = req.uri().query().unwrap_or("").to_string();

    let headers = collect_forward_headers(req.headers());

    // Read body
    let body_bytes = match axum::body::to_bytes(req.into_body(), max_body_bytes).await {
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

    // Bind the staged file to a RAII guard immediately so it gets cleaned up
    // on every exit path — including future cancellation if the client
    // disconnects mid-request. The guard outlives the `ipc.request` await,
    // so Python is guaranteed to have read the file by the time we delete.
    let _staged_guard = StagedBodyGuard::new(staged_body_path);

    match ipc.request("api.forward", Some(params)).await {
        Ok(result) => build_response_from_ipc(result),
        Err(e) => (StatusCode::BAD_GATEWAY, format!("IPC error: {e}")).into_response(),
    }
}

fn collect_forward_headers(
    request_headers: &axum::http::HeaderMap,
) -> serde_json::Map<String, Value> {
    let mut headers = serde_json::Map::new();
    for (name, value) in request_headers {
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
    headers
}

#[derive(Debug, PartialEq, Eq)]
enum StageBodyError {
    TooLarge,
    Read,
    Io,
}

async fn stream_body_to_file(
    mut body: Body,
    file: &mut tokio::fs::File,
    max_body_bytes: usize,
) -> Result<(), StageBodyError> {
    let mut total_bytes = 0usize;
    while let Some(frame) = body.frame().await {
        let frame = frame.map_err(|_| StageBodyError::Read)?;
        let Ok(data) = frame.into_data() else {
            continue;
        };
        total_bytes = total_bytes
            .checked_add(data.len())
            .ok_or(StageBodyError::TooLarge)?;
        if total_bytes > max_body_bytes {
            return Err(StageBodyError::TooLarge);
        }
        file.write_all(&data)
            .await
            .map_err(|_| StageBodyError::Io)?;
    }
    file.flush().await.map_err(|_| StageBodyError::Io)?;
    Ok(())
}

fn build_staged_ipc_params(
    method: String,
    path: String,
    query: String,
    headers: serde_json::Map<String, Value>,
    staged_path: &std::path::Path,
) -> Value {
    serde_json::json!({
        "method": method,
        "path": path,
        "query": query,
        "headers": headers,
        "body_file_path": staged_path.to_string_lossy(),
    })
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
    let path = new_staged_body_path();
    let mut file = create_secure_staged_file(&path)?;
    let mut guard = StagedBodyGuard::new(Some(path.clone()));
    let write_result = file.write_all(body_bytes).and_then(|_| file.flush());
    drop(file);
    write_result?;
    guard.disarm();
    Ok(path)
}

fn new_staged_body_path() -> PathBuf {
    std::env::temp_dir().join(format!("{BODY_FILE_PREFIX}{}", uuid::Uuid::new_v4()))
}

fn create_secure_staged_file(path: &std::path::Path) -> std::io::Result<fs::File> {
    let mut options = fs::OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options.open(path)
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
    use super::{
        build_ipc_params, build_response_from_ipc, create_secure_staged_file, stream_body_to_file,
        StageBodyError, StagedBodyGuard, BODY_FILE_PREFIX,
    };
    use axum::body::{Body, Bytes};
    use axum::http::StatusCode;
    use futures_util::stream;
    use http_body_util::BodyExt;
    use serde_json::json;
    use std::convert::Infallible;
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    };

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
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(&staged_path)
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o600
            );
        }
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

    #[tokio::test]
    async fn streams_request_chunks_directly_to_staged_file() {
        let staged_path =
            std::env::temp_dir().join(format!("{BODY_FILE_PREFIX}test-{}", uuid::Uuid::new_v4()));
        let chunks = [b"alpha".as_slice(), b"-".as_slice(), b"omega".as_slice()]
            .into_iter()
            .map(|chunk| Ok::<Bytes, Infallible>(Bytes::copy_from_slice(chunk)));
        let body = Body::from_stream(stream::iter(chunks));
        let staged_file =
            tokio::fs::File::from_std(create_secure_staged_file(&staged_path).unwrap());
        let mut guard = StagedBodyGuard::with_streaming_file(staged_path.clone(), staged_file);

        stream_body_to_file(body, guard.streaming_file_mut(), 32)
            .await
            .expect("stream staged body");
        guard.close_streaming_file();

        assert_eq!(std::fs::read(&staged_path).unwrap(), b"alpha-omega");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(&staged_path)
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o600
            );
        }
        drop(guard);
        assert!(!staged_path.exists());
    }

    #[tokio::test]
    async fn streaming_limit_stops_polling_and_guard_cleans_partial_file() {
        let staged_path =
            std::env::temp_dir().join(format!("{BODY_FILE_PREFIX}test-{}", uuid::Uuid::new_v4()));
        let chunks_polled = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&chunks_polled);
        let chunks = (0..10).map(move |_| {
            observed.fetch_add(1, Ordering::SeqCst);
            Ok::<Bytes, Infallible>(Bytes::from_static(b"1234"))
        });
        let body = Body::from_stream(stream::iter(chunks));
        let staged_file =
            tokio::fs::File::from_std(create_secure_staged_file(&staged_path).unwrap());
        let mut guard = StagedBodyGuard::with_streaming_file(staged_path.clone(), staged_file);

        let result = stream_body_to_file(body, guard.streaming_file_mut(), 9).await;

        assert_eq!(result, Err(StageBodyError::TooLarge));
        assert_eq!(chunks_polled.load(Ordering::SeqCst), 3);
        guard.close_streaming_file();
        assert_eq!(std::fs::read(&staged_path).unwrap(), b"12341234");
        drop(guard);
        assert!(!staged_path.exists());
    }

    #[tokio::test]
    async fn cancelling_stream_closes_file_before_temp_cleanup() {
        let staged_path =
            std::env::temp_dir().join(format!("{BODY_FILE_PREFIX}test-{}", uuid::Uuid::new_v4()));
        let staged_file =
            tokio::fs::File::from_std(create_secure_staged_file(&staged_path).unwrap());
        let mut guard = StagedBodyGuard::with_streaming_file(staged_path.clone(), staged_file);
        let body = Body::from_stream(stream::pending::<Result<Bytes, Infallible>>());

        let streaming =
            tokio::spawn(
                async move { stream_body_to_file(body, guard.streaming_file_mut(), 32).await },
            );
        tokio::task::yield_now().await;
        streaming.abort();
        assert!(streaming.await.is_err());
        assert!(!staged_path.exists());
    }
}
