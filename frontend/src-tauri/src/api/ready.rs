use axum::Json;
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::db;

const HEARTBEAT_ROLE: &str = "runtime_worker";
const HEARTBEAT_STALE_AFTER_MS: i64 = 15_000;
const PENDING_COMMAND_WARNING_THRESHOLD: i64 = 100;

/// Native GET /api/ready handler — reads runtime_trace.db directly.
pub async fn ready() -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || build_ready_response())
        .await
        .unwrap_or_else(|_| {
            json!({
                "success": true,
                "message": "Backend startup state",
                "data": {
                    "ready": false,
                    "status": "degraded",
                    "api_ready": true,
                    "runtime_ready": false,
                    "runtime_status": "offline",
                    "process_role": "unified"
                }
            })
        });
    Json(result)
}

fn build_ready_response() -> Value {
    let db_path = db::runtime_trace_db_path();
    if !db_path.exists() {
        return ready_payload(false, "offline", None, None);
    }

    let conn = match Connection::open_with_flags(&db_path, OpenFlags::SQLITE_OPEN_READ_ONLY) {
        Ok(c) => c,
        Err(_) => return ready_payload(false, "offline", None, None),
    };

    // Read heartbeat
    let heartbeat = conn.query_row(
        "SELECT status, last_seen_at_ms, queue_backlog FROM runtime_heartbeats WHERE role = ?1",
        [HEARTBEAT_ROLE],
        |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, i64>(2)?,
            ))
        },
    );

    let (runtime_ready, runtime_status, heartbeat_age_ms, queue_backlog) = match heartbeat {
        Ok((status, last_seen_at_ms, backlog)) => {
            let now_ms = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_millis() as i64)
                .unwrap_or(0);
            let age_ms = (now_ms - last_seen_at_ms).max(0);
            if age_ms > HEARTBEAT_STALE_AFTER_MS {
                (false, "stale".to_string(), Some(age_ms), Some(backlog))
            } else {
                let ready = status == "ready";
                (ready, status, Some(age_ms), Some(backlog))
            }
        }
        Err(_) => (false, "offline".to_string(), None, None),
    };

    // Read pending command count
    let pending_commands = conn
        .query_row(
            "SELECT COUNT(*) FROM runtime_notifications WHERE notification_id > (SELECT COALESCE(MAX(notification_id), 0) - 1000 FROM runtime_notifications)",
            [],
            |row| row.get::<_, i64>(0),
        )
        .ok();

    let queue_backlog_healthy = queue_backlog
        .map(|b| b <= PENDING_COMMAND_WARNING_THRESHOLD)
        .unwrap_or(true);

    let status = if runtime_ready && queue_backlog_healthy {
        "ready"
    } else {
        "degraded"
    };

    json!({
        "success": true,
        "message": "Backend startup state",
        "data": {
            "ready": status == "ready",
            "status": status,
            "api_ready": true,
            "runtime_ready": runtime_ready,
            "runtime_status": runtime_status,
            "runtime_heartbeat_age_ms": heartbeat_age_ms,
            "queue_backlog_healthy": queue_backlog_healthy,
            "pending_commands": pending_commands,
            "process_role": "unified"
        }
    })
}

fn ready_payload(
    runtime_ready: bool,
    runtime_status: &str,
    heartbeat_age_ms: Option<i64>,
    pending_commands: Option<i64>,
) -> Value {
    let status = if runtime_ready { "ready" } else { "degraded" };
    json!({
        "success": true,
        "message": "Backend startup state",
        "data": {
            "ready": status == "ready",
            "status": status,
            "api_ready": true,
            "runtime_ready": runtime_ready,
            "runtime_status": runtime_status,
            "runtime_heartbeat_age_ms": heartbeat_age_ms,
            "queue_backlog_healthy": true,
            "pending_commands": pending_commands,
            "process_role": "unified"
        }
    })
}
