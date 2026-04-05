use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::db;

#[derive(Deserialize)]
pub struct ListSchedulesQuery {
    pub enabled_only: Option<bool>,
}

#[derive(Deserialize)]
pub struct ExecutionsQuery {
    pub limit: Option<i64>,
}

/// Native GET /api/schedules handler.
pub async fn list_schedules(Query(params): Query<ListSchedulesQuery>) -> Json<Value> {
    let enabled_only = params.enabled_only.unwrap_or(false);
    let result = tokio::task::spawn_blocking(move || query_schedules(enabled_only))
        .await
        .unwrap_or_else(|_| json!({"schedules": []}));
    Json(result)
}

/// Native GET /api/schedules/:schedule_id handler.
pub async fn get_schedule(Path(schedule_id): Path<String>) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || query_single_schedule(&schedule_id))
        .await
        .unwrap_or(None);
    match result {
        Some(v) => (StatusCode::OK, Json(v)),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({"detail": "Schedule not found"})),
        ),
    }
}

/// Native GET /api/schedules/:schedule_id/executions handler.
pub async fn list_schedule_executions(
    Path(schedule_id): Path<String>,
    Query(params): Query<ExecutionsQuery>,
) -> Json<Value> {
    let limit = params.limit.unwrap_or(20).clamp(1, 100);
    let result =
        tokio::task::spawn_blocking(move || query_executions(Some(&schedule_id), limit))
            .await
            .unwrap_or_else(|_| json!({"executions": []}));
    Json(result)
}

/// Native GET /api/schedules/executions/recent handler.
pub async fn list_recent_executions(Query(params): Query<ExecutionsQuery>) -> Json<Value> {
    let limit = params.limit.unwrap_or(20).clamp(1, 100);
    let result = tokio::task::spawn_blocking(move || query_executions(None, limit))
        .await
        .unwrap_or_else(|_| json!({"executions": []}));
    Json(result)
}

fn open_scheduler_db() -> Option<Connection> {
    let path = db::scheduler_db_path();
    if !path.exists() {
        return None;
    }
    Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY).ok()
}

fn open_scheduler_db_rw() -> Option<Connection> {
    db::open_readwrite(&db::scheduler_db_path())
}

fn serialize_schedule(row: &rusqlite::Row) -> rusqlite::Result<Value> {
    let trigger_config: String = row.get::<_, Option<String>>(4)?.unwrap_or_else(|| "{}".into());
    let target_payload: String = row.get::<_, Option<String>>(5)?.unwrap_or_else(|| "{}".into());
    let metadata: String = row.get::<_, Option<String>>(6)?.unwrap_or_else(|| "{}".into());
    Ok(json!({
        "schedule_id": row.get::<_, String>(0)?,
        "target_type": row.get::<_, String>(1)?,
        "target_key": row.get::<_, String>(2)?,
        "trigger": {
            "trigger_type": row.get::<_, String>(3)?,
            "config": serde_json::from_str::<Value>(&trigger_config).unwrap_or(json!({})),
        },
        "target_payload": serde_json::from_str::<Value>(&target_payload).unwrap_or(json!({})),
        "enabled": row.get::<_, i64>(7)? != 0,
        "metadata": serde_json::from_str::<Value>(&metadata).unwrap_or(json!({})),
        "job_id": row.get::<_, Option<String>>(8)?,
    }))
}

const SCHEDULE_COLUMNS: &str = "schedule_id, target_type, target_key, trigger_type, \
    trigger_config, target_payload, metadata, enabled, job_id";

fn query_schedules(enabled_only: bool) -> Value {
    let conn = match open_scheduler_db() {
        Some(c) => c,
        None => return json!({"schedules": []}),
    };
    let query = if enabled_only {
        format!(
            "SELECT {} FROM schedules WHERE enabled = 1",
            SCHEDULE_COLUMNS
        )
    } else {
        format!("SELECT {} FROM schedules", SCHEDULE_COLUMNS)
    };
    let mut stmt = match conn.prepare(&query) {
        Ok(s) => s,
        Err(_) => return json!({"schedules": []}),
    };
    let schedules: Vec<Value> = stmt
        .query_map([], serialize_schedule)
        .ok()
        .map(|iter| iter.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();
    json!({"schedules": schedules})
}

fn query_single_schedule(schedule_id: &str) -> Option<Value> {
    let conn = open_scheduler_db()?;
    let mut stmt = conn
        .prepare(&format!(
            "SELECT {} FROM schedules WHERE schedule_id = ?1",
            SCHEDULE_COLUMNS
        ))
        .ok()?;
    let schedule = stmt
        .query_row(rusqlite::params![schedule_id], serialize_schedule)
        .ok()?;

    // Load target_state
    let target_type = schedule
        .get("target_type")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let target_key = schedule
        .get("target_key")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let target_state = query_target_state(&conn, target_type, target_key);

    Some(json!({
        "schedule": schedule,
        "target_state": target_state,
    }))
}

fn query_target_state(conn: &Connection, target_type: &str, target_key: &str) -> Value {
    let mut stmt = match conn.prepare(
        "SELECT running, last_run_at, last_success_at, last_error, last_cursor, \
         watermark_ts, next_run_at, scheduler_job_id, stats_json, updated_at \
         FROM target_state WHERE target_type = ?1 AND target_key = ?2",
    ) {
        Ok(s) => s,
        Err(_) => {
            return json!({
                "target_type": target_type,
                "target_key": target_key,
                "running": false,
            })
        }
    };
    match stmt.query_row(rusqlite::params![target_type, target_key], |row| {
        let stats_json: String = row.get::<_, Option<String>>(8)?.unwrap_or_else(|| "{}".into());
        Ok(json!({
            "target_type": target_type,
            "target_key": target_key,
            "running": row.get::<_, i64>(0)? != 0,
            "last_run_at": row.get::<_, Option<f64>>(1)?,
            "last_success_at": row.get::<_, Option<f64>>(2)?,
            "last_error": row.get::<_, Option<String>>(3)?,
            "last_cursor": row.get::<_, Option<String>>(4)?,
            "watermark_ts": row.get::<_, Option<f64>>(5)?,
            "next_run_at": row.get::<_, Option<f64>>(6)?,
            "scheduler_job_id": row.get::<_, Option<String>>(7)?,
            "stats": serde_json::from_str::<Value>(&stats_json).unwrap_or(json!({})),
            "updated_at": row.get::<_, Option<f64>>(9)?,
        }))
    }) {
        Ok(v) => v,
        Err(_) => json!({
            "target_type": target_type,
            "target_key": target_key,
            "running": false,
        }),
    }
}

const EXECUTION_COLUMNS: &str = "execution_id, schedule_id, target_type, target_key, manual, \
    status, started_at, finished_at, duration_ms, result_message, error, \
    stats_json, next_cursor, watermark_ts, scheduler_job_id, created_at";

fn serialize_execution(row: &rusqlite::Row) -> rusqlite::Result<Value> {
    let stats_json: String = row
        .get::<_, Option<String>>(11)?
        .unwrap_or_else(|| "{}".into());
    Ok(json!({
        "execution_id": row.get::<_, String>(0)?,
        "schedule_id": row.get::<_, String>(1)?,
        "target_type": row.get::<_, String>(2)?,
        "target_key": row.get::<_, String>(3)?,
        "manual": row.get::<_, i64>(4)? != 0,
        "status": row.get::<_, String>(5)?,
        "started_at": row.get::<_, Option<f64>>(6)?,
        "finished_at": row.get::<_, Option<f64>>(7)?,
        "duration_ms": row.get::<_, Option<f64>>(8)?,
        "result_message": row.get::<_, Option<String>>(9)?,
        "error": row.get::<_, Option<String>>(10)?,
        "stats": serde_json::from_str::<Value>(&stats_json).unwrap_or(json!({})),
        "next_cursor": row.get::<_, Option<String>>(12)?,
        "watermark_ts": row.get::<_, Option<f64>>(13)?,
        "scheduler_job_id": row.get::<_, Option<String>>(14)?,
        "created_at": row.get::<_, Option<f64>>(15)?,
    }))
}

fn query_executions(schedule_id: Option<&str>, limit: i64) -> Value {
    let conn = match open_scheduler_db() {
        Some(c) => c,
        None => return json!({"executions": []}),
    };
    let (query, params): (String, Vec<Box<dyn rusqlite::types::ToSql>>) =
        if let Some(sid) = schedule_id {
            (
                format!(
                    "SELECT {} FROM schedule_executions WHERE schedule_id = ?1 ORDER BY started_at DESC LIMIT ?2",
                    EXECUTION_COLUMNS
                ),
                vec![Box::new(sid.to_string()), Box::new(limit)],
            )
        } else {
            (
                format!(
                    "SELECT {} FROM schedule_executions ORDER BY started_at DESC LIMIT ?1",
                    EXECUTION_COLUMNS
                ),
                vec![Box::new(limit)],
            )
        };
    let mut stmt = match conn.prepare(&query) {
        Ok(s) => s,
        Err(_) => return json!({"executions": []}),
    };
    let param_refs: Vec<&dyn rusqlite::types::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    let executions: Vec<Value> = stmt
        .query_map(param_refs.as_slice(), serialize_execution)
        .ok()
        .map(|iter| iter.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();
    json!({"executions": executions})
}

// ---------------------------------------------------------------------------
// Mutation handlers
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct ScheduleTrigger {
    pub trigger_type: String,
    pub config: Value,
}

#[derive(Deserialize)]
pub struct ScheduleCreateBody {
    pub schedule_id: String,
    pub target_type: String,
    pub target_key: String,
    pub trigger: ScheduleTrigger,
    pub target_payload: Option<Value>,
    pub enabled: Option<bool>,
    pub metadata: Option<Value>,
}

pub async fn create_schedule(
    Json(body): Json<ScheduleCreateBody>,
) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || upsert_schedule(body))
        .await
        .unwrap_or(None);
    match result {
        Some(schedule) => (StatusCode::CREATED, Json(json!({"schedule": schedule}))),
        None => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"detail": "Failed to create schedule"})),
        ),
    }
}

fn upsert_schedule(body: ScheduleCreateBody) -> Option<Value> {
    let conn = open_scheduler_db_rw()?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_secs_f64();
    let trigger_config = serde_json::to_string(&body.trigger.config).unwrap_or_else(|_| "{}".to_string());
    let target_payload = serde_json::to_string(&body.target_payload.unwrap_or(json!({}))).unwrap_or_else(|_| "{}".to_string());
    let metadata = serde_json::to_string(&body.metadata.unwrap_or(json!({}))).unwrap_or_else(|_| "{}".to_string());
    let enabled: i64 = if body.enabled.unwrap_or(true) { 1 } else { 0 };

    conn.execute(
        "INSERT INTO schedules (schedule_id, target_type, target_key, trigger_type, trigger_config, \
         target_payload, metadata, enabled, created_at, updated_at) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10) \
         ON CONFLICT(schedule_id) DO UPDATE SET \
         target_type=excluded.target_type, target_key=excluded.target_key, \
         trigger_type=excluded.trigger_type, trigger_config=excluded.trigger_config, \
         target_payload=excluded.target_payload, metadata=excluded.metadata, \
         enabled=excluded.enabled, updated_at=excluded.updated_at",
        rusqlite::params![
            body.schedule_id,
            body.target_type,
            body.target_key,
            body.trigger.trigger_type,
            trigger_config,
            target_payload,
            metadata,
            enabled,
            now,
            now,
        ],
    )
    .ok()?;

    // Ensure target_state row exists
    conn.execute(
        "INSERT OR IGNORE INTO target_state (target_type, target_key, updated_at) VALUES (?1, ?2, ?3)",
        rusqlite::params![body.target_type, body.target_key, now],
    )
    .ok();

    // Read back
    let mut stmt = conn
        .prepare(&format!(
            "SELECT {} FROM schedules WHERE schedule_id = ?1",
            SCHEDULE_COLUMNS
        ))
        .ok()?;
    stmt.query_row(rusqlite::params![body.schedule_id], serialize_schedule)
        .ok()
}

#[derive(Deserialize)]
pub struct ScheduleUpdateBody {
    pub trigger: Option<ScheduleTrigger>,
    pub target_payload: Option<Value>,
    pub enabled: Option<bool>,
    pub metadata: Option<Value>,
}

pub async fn update_schedule(
    Path(schedule_id): Path<String>,
    Json(body): Json<ScheduleUpdateBody>,
) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || patch_schedule(&schedule_id, body))
        .await
        .unwrap_or(None);
    match result {
        Some(schedule) => (StatusCode::OK, Json(json!({"schedule": schedule}))),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({"detail": "Schedule not found"})),
        ),
    }
}

fn patch_schedule(schedule_id: &str, body: ScheduleUpdateBody) -> Option<Value> {
    let conn = open_scheduler_db_rw()?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_secs_f64();

    let mut sets = Vec::new();
    let mut params: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
    let mut idx = 1;

    if let Some(trigger) = body.trigger {
        sets.push(format!("trigger_type = ?{}", idx));
        params.push(Box::new(trigger.trigger_type));
        idx += 1;
        let config_str = serde_json::to_string(&trigger.config).unwrap_or_else(|_| "{}".to_string());
        sets.push(format!("trigger_config = ?{}", idx));
        params.push(Box::new(config_str));
        idx += 1;
    }
    if let Some(payload) = body.target_payload {
        let s = serde_json::to_string(&payload).unwrap_or_else(|_| "{}".to_string());
        sets.push(format!("target_payload = ?{}", idx));
        params.push(Box::new(s));
        idx += 1;
    }
    if let Some(enabled) = body.enabled {
        sets.push(format!("enabled = ?{}", idx));
        params.push(Box::new(if enabled { 1i64 } else { 0i64 }));
        idx += 1;
    }
    if let Some(meta) = body.metadata {
        let s = serde_json::to_string(&meta).unwrap_or_else(|_| "{}".to_string());
        sets.push(format!("metadata = ?{}", idx));
        params.push(Box::new(s));
        idx += 1;
    }

    if sets.is_empty() {
        // No fields to update; read back existing
        let mut stmt = conn
            .prepare(&format!(
                "SELECT {} FROM schedules WHERE schedule_id = ?1",
                SCHEDULE_COLUMNS
            ))
            .ok()?;
        return stmt
            .query_row(rusqlite::params![schedule_id], serialize_schedule)
            .ok();
    }

    sets.push(format!("updated_at = ?{}", idx));
    params.push(Box::new(now));
    idx += 1;

    let sql = format!(
        "UPDATE schedules SET {} WHERE schedule_id = ?{}",
        sets.join(", "),
        idx
    );
    params.push(Box::new(schedule_id.to_string()));

    let param_refs: Vec<&dyn rusqlite::types::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    let updated = conn.execute(&sql, param_refs.as_slice()).unwrap_or(0);
    if updated == 0 {
        return None;
    }

    let mut stmt = conn
        .prepare(&format!(
            "SELECT {} FROM schedules WHERE schedule_id = ?1",
            SCHEDULE_COLUMNS
        ))
        .ok()?;
    stmt.query_row(rusqlite::params![schedule_id], serialize_schedule)
        .ok()
}

pub async fn delete_schedule(Path(schedule_id): Path<String>) -> StatusCode {
    let result = tokio::task::spawn_blocking(move || remove_schedule(&schedule_id))
        .await
        .unwrap_or(false);
    if result {
        StatusCode::NO_CONTENT
    } else {
        StatusCode::NOT_FOUND
    }
}

fn remove_schedule(schedule_id: &str) -> bool {
    let conn = match open_scheduler_db_rw() {
        Some(c) => c,
        None => return false,
    };
    // Clear target_state binding
    conn.execute(
        "UPDATE target_state SET next_run_at = NULL, scheduler_job_id = NULL, \
         running = 0, last_error = NULL, updated_at = ?1 \
         WHERE (target_type, target_key) IN \
         (SELECT target_type, target_key FROM schedules WHERE schedule_id = ?2)",
        rusqlite::params![
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64(),
            schedule_id,
        ],
    )
    .ok();
    // Delete schedule
    conn.execute(
        "DELETE FROM schedules WHERE schedule_id = ?1",
        rusqlite::params![schedule_id],
    )
    .map(|n| n > 0)
    .unwrap_or(false)
}
