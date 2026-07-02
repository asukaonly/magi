use axum::{extract::State, Json};
use serde_json::{json, Value};
use std::time::Duration;

use super::state::ApiState;

const READY_IPC_TIMEOUT_MS: u64 = 1_000;

/// Native GET /api/ready handler — asks the Python worker over IPC with a short bound.
pub async fn ready(State(state): State<ApiState>) -> Json<Value> {
    let timeout = Duration::from_millis(READY_IPC_TIMEOUT_MS);
    let result = match state
        .ipc_client
        .request_with_timeout("runtime.ready", None, timeout)
        .await
    {
        Ok(value) => value,
        Err(err) => unresponsive_payload(err.to_string()),
    };
    Json(result)
}

fn unresponsive_payload(reason: String) -> Value {
    json!({
        "success": true,
        "message": "Backend startup state",
        "data": {
            "ready": false,
            "status": "degraded",
            "runtime_ready": false,
            "worker_ready": false,
            "llm_ready": null,
            "agent_runtime_ready": null,
            "runtime_status": "unresponsive",
            "startup_state": "unresponsive",
            "deferred_reason": reason
        }
    })
}
