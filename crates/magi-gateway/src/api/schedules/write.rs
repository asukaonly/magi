use serde_json::{json, Value};

use crate::db;

use super::storage::{serialize_schedule, SCHEDULE_COLUMNS};
use super::types::{ScheduleCreateBody, ScheduleUpdateBody};

pub(super) fn upsert_schedule(body: ScheduleCreateBody) -> Option<Value> {
    let conn = open_scheduler_db_rw()?;
    let now = now_seconds()?;
    let trigger_config =
        serde_json::to_string(&body.trigger.config).unwrap_or_else(|_| "{}".to_string());
    let target_payload = serde_json::to_string(&body.target_payload.unwrap_or(json!({})))
        .unwrap_or_else(|_| "{}".to_string());
    let metadata = serde_json::to_string(&body.metadata.unwrap_or(json!({})))
        .unwrap_or_else(|_| "{}".to_string());
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

    conn.execute(
        "INSERT OR IGNORE INTO target_state (target_type, target_key, updated_at) VALUES (?1, ?2, ?3)",
        rusqlite::params![body.target_type, body.target_key, now],
    )
    .ok();

    let mut stmt = conn
        .prepare(&format!(
            "SELECT {} FROM schedules WHERE schedule_id = ?1",
            SCHEDULE_COLUMNS
        ))
        .ok()?;
    stmt.query_row(rusqlite::params![body.schedule_id], serialize_schedule)
        .ok()
}

pub(super) fn patch_schedule(schedule_id: &str, body: ScheduleUpdateBody) -> Option<Value> {
    let conn = open_scheduler_db_rw()?;
    let now = now_seconds()?;

    let mut sets = Vec::new();
    let mut params: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
    let mut idx = 1;

    if let Some(trigger) = body.trigger {
        sets.push(format!("trigger_type = ?{}", idx));
        params.push(Box::new(trigger.trigger_type));
        idx += 1;
        let config_str =
            serde_json::to_string(&trigger.config).unwrap_or_else(|_| "{}".to_string());
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

pub(super) fn remove_schedule(schedule_id: &str) -> bool {
    let conn = match open_scheduler_db_rw() {
        Some(c) => c,
        None => return false,
    };
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
    conn.execute(
        "DELETE FROM schedules WHERE schedule_id = ?1",
        rusqlite::params![schedule_id],
    )
    .map(|n| n > 0)
    .unwrap_or(false)
}

pub(super) fn cancel_queued_activity(activity_id: &str, reason: &str) -> Option<Value> {
    let job_id = activity_id.strip_prefix("source_job:")?;
    let conn = open_scheduler_db_rw()?;
    let finished_at = now_seconds()?;
    let row = conn
        .query_row(
            "SELECT execution_id, started_at FROM source_sync_jobs WHERE job_id = ?1 AND status = 'queued'",
            rusqlite::params![job_id],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, Option<f64>>(1)?)),
        )
        .ok()?;
    let started_at = row.1.unwrap_or(finished_at);
    let updated = conn
        .execute(
            "UPDATE source_sync_jobs SET status = 'cancelled', finished_at = ?1, error = NULL, result_message = ?2 \
             WHERE job_id = ?3 AND status = 'queued'",
            rusqlite::params![finished_at, reason, job_id],
        )
        .ok()?;
    if updated == 0 {
        return None;
    }
    conn.execute(
        "UPDATE schedule_executions SET status = 'cancelled', finished_at = ?1, duration_ms = ?2, result_message = ?3 \
         WHERE execution_id = ?4 AND status = 'running'",
        rusqlite::params![
            finished_at,
            (finished_at - started_at).max(0.0) * 1000.0,
            reason,
            row.0,
        ],
    )
    .ok();
    Some(json!({
        "activity_id": activity_id,
        "status": "cancelled",
        "job_id": job_id,
    }))
}

fn now_seconds() -> Option<f64> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()
        .map(|duration| duration.as_secs_f64())
}

fn open_scheduler_db_rw() -> Option<rusqlite::Connection> {
    db::open_readwrite(&db::scheduler_db_path())
}
