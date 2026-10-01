use axum::{extract::State, Json};
use magi_service_contract::lifecycle::{SupervisorPhase, SupervisorStatus};
use serde_json::{json, Value};
use std::time::Duration;

use super::state::ApiState;
use crate::ipc::protocol::IpcError;

const READY_IPC_TIMEOUT_MS: u64 = 1_000;

/// Native GET /api/ready handler — asks the Python worker over IPC with a short bound.
pub async fn ready(State(state): State<ApiState>) -> Json<Value> {
    Json(load_readiness(&state).await)
}

pub(super) async fn load_readiness(state: &ApiState) -> Value {
    let timeout = Duration::from_millis(READY_IPC_TIMEOUT_MS);
    match state
        .ipc_client
        .request_with_timeout("runtime.ready", None, timeout)
        .await
    {
        Ok(value) => value,
        Err(err) => {
            let supervisor = state.supervisor.read().unwrap_or_else(|e| e.into_inner());
            unavailable_payload(&err, &supervisor)
        }
    }
}

fn unavailable_payload(error: &IpcError, supervisor: &SupervisorStatus) -> Value {
    let runtime_status = match supervisor.phase {
        SupervisorPhase::Backoff | SupervisorPhase::Cooldown => "recovering",
        SupervisorPhase::Starting if supervisor.restart_count > 0 => "recovering",
        _ => match error.code {
            -3 | -4 => "disconnected",
            -5 | -32002 => {
                if matches!(supervisor.phase, SupervisorPhase::Unresponsive) {
                    "unresponsive"
                } else {
                    "probe_timeout"
                }
            }
            -32001 => "probe_busy",
            _ => "probe_failed",
        },
    };
    json!({
        "success": true,
        "message": "Backend startup state",
        "data": {
            "ready": false,
            "status": "degraded",
            "service_ready": false,
            "storage_ready": false,
            "capabilities": {},
            "runtime_ready": false,
            "worker_ready": false,
            "llm_ready": null,
            "agent_runtime_ready": null,
            "runtime_status": runtime_status,
            "startup_state": runtime_status,
            "deferred_reason": error.to_string()
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn failed_readiness_preserves_the_evidence_and_recovery_state() {
        for (code, phase, restarts, expected) in [
            (-5, SupervisorPhase::Ready, 0, "probe_timeout"),
            (-32002, SupervisorPhase::Ready, 0, "probe_timeout"),
            (-5, SupervisorPhase::Unresponsive, 0, "unresponsive"),
            (-4, SupervisorPhase::Unresponsive, 0, "disconnected"),
            (-3, SupervisorPhase::Ready, 0, "disconnected"),
            (-4, SupervisorPhase::Starting, 0, "disconnected"),
            (-32001, SupervisorPhase::Unresponsive, 0, "probe_busy"),
            (-32000, SupervisorPhase::Ready, 0, "probe_failed"),
            (-4, SupervisorPhase::Backoff, 1, "recovering"),
            (-4, SupervisorPhase::Cooldown, 3, "recovering"),
            (-4, SupervisorPhase::Starting, 1, "recovering"),
            (-4, SupervisorPhase::Failed, 3, "disconnected"),
        ] {
            let error = IpcError {
                code,
                message: "Probe diagnostic".into(),
            };
            let supervisor = SupervisorStatus {
                phase,
                restart_count: restarts,
                ..Default::default()
            };
            let payload = unavailable_payload(&error, &supervisor);
            assert_eq!(payload["data"]["runtime_status"], expected);
            assert_eq!(payload["data"]["startup_state"], expected);
            assert_eq!(payload["data"]["ready"], false);
            assert_eq!(payload["data"]["deferred_reason"], error.to_string());
        }
    }
}
