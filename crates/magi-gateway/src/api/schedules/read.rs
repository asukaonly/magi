use rusqlite::Connection;
use serde_json::{json, Value};

use super::storage::{open_scheduler_db, serialize_schedule, SCHEDULE_COLUMNS};

pub(super) fn query_schedules(enabled_only: bool) -> Value {
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
    let mut schedules: Vec<Value> = stmt
        .query_map([], serialize_schedule)
        .ok()
        .map(|iter| iter.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();
    for schedule in schedules.iter_mut() {
        let schedule_id = schedule
            .get("schedule_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let target_type = schedule
            .get("target_type")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let target_key = schedule
            .get("target_key")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let job_id = schedule
            .get("job_id")
            .and_then(|v| v.as_str())
            .unwrap_or(schedule_id);
        schedule["target_state"] =
            query_schedule_runtime_state(&conn, schedule_id, target_type, target_key, job_id);
    }
    json!({"schedules": schedules})
}

pub(super) fn query_single_schedule(schedule_id: &str) -> Option<Value> {
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

    let target_type = schedule
        .get("target_type")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let target_key = schedule
        .get("target_key")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let job_id = schedule
        .get("job_id")
        .and_then(|v| v.as_str())
        .unwrap_or(schedule_id);
    let target_state =
        query_schedule_runtime_state(&conn, schedule_id, target_type, target_key, job_id);

    Some(json!({
        "schedule": schedule,
        "target_state": target_state,
    }))
}

fn query_schedule_runtime_state(
    conn: &Connection,
    schedule_id: &str,
    target_type: &str,
    target_key: &str,
    job_id: &str,
) -> Value {
    let base = query_target_state(conn, target_type, target_key);
    let target_running = base
        .get("running")
        .and_then(|value| value.as_bool())
        .unwrap_or(false);
    let mut next_run_at = query_job_next_run_at(conn, job_id);
    if next_run_at.is_null()
        && base
            .get("scheduler_job_id")
            .and_then(|value| value.as_str())
            == Some(job_id)
    {
        next_run_at = base.get("next_run_at").cloned().unwrap_or(Value::Null);
    }
    let mut stmt = match conn.prepare(
        "SELECT status, started_at, finished_at, error, stats_json, next_cursor, watermark_ts, scheduler_job_id \
         FROM schedule_executions WHERE schedule_id = ?1 ORDER BY started_at DESC LIMIT 1",
    ) {
        Ok(stmt) => stmt,
        Err(_) => {
            return json!({
                "target_type": target_type,
                "target_key": target_key,
                "running": target_running,
                "last_run_at": Value::Null,
                "last_success_at": Value::Null,
                "last_error": Value::Null,
                "last_cursor": Value::Null,
                "watermark_ts": Value::Null,
                "next_run_at": next_run_at,
                "scheduler_job_id": job_id,
                "stats": json!({}),
                "updated_at": base.get("updated_at").cloned().unwrap_or(Value::Null),
            })
        }
    };
    let latest = stmt.query_row(rusqlite::params![schedule_id], |row| {
        let stats_json: String = row
            .get::<_, Option<String>>(4)?
            .unwrap_or_else(|| "{}".into());
        Ok(json!({
            "status": row.get::<_, String>(0)?,
            "started_at": row.get::<_, Option<f64>>(1)?,
            "finished_at": row.get::<_, Option<f64>>(2)?,
            "error": row.get::<_, Option<String>>(3)?,
            "stats": serde_json::from_str::<Value>(&stats_json).unwrap_or(json!({})),
            "next_cursor": row.get::<_, Option<String>>(5)?,
            "watermark_ts": row.get::<_, Option<f64>>(6)?,
            "scheduler_job_id": row.get::<_, Option<String>>(7)?.unwrap_or_else(|| job_id.to_string()),
        }))
    });
    match latest {
        Ok(row) => {
            let status = row.get("status").and_then(|v| v.as_str()).unwrap_or("");
            let started_at = row.get("started_at").cloned().unwrap_or(Value::Null);
            let finished_at = row.get("finished_at").cloned().unwrap_or(Value::Null);
            let updated_at = if !finished_at.is_null() {
                finished_at.clone()
            } else {
                started_at.clone()
            };
            json!({
                "target_type": target_type,
                "target_key": target_key,
                "running": target_running,
                "last_run_at": started_at,
                "last_success_at": if status == "success" { finished_at.clone() } else { Value::Null },
                "last_error": row.get("error").cloned().unwrap_or(Value::Null),
                "last_cursor": row.get("next_cursor").cloned().unwrap_or(Value::Null),
                "watermark_ts": row.get("watermark_ts").cloned().unwrap_or(Value::Null),
                "next_run_at": next_run_at,
                "scheduler_job_id": row.get("scheduler_job_id").cloned().unwrap_or_else(|| Value::String(job_id.to_string())),
                "stats": row.get("stats").cloned().unwrap_or_else(|| json!({})),
                "updated_at": updated_at,
            })
        }
        Err(_) => json!({
            "target_type": target_type,
            "target_key": target_key,
            "running": target_running,
            "last_run_at": Value::Null,
            "last_success_at": Value::Null,
            "last_error": Value::Null,
            "last_cursor": Value::Null,
            "watermark_ts": Value::Null,
            "next_run_at": next_run_at,
            "scheduler_job_id": job_id,
            "stats": json!({}),
            "updated_at": base.get("updated_at").cloned().unwrap_or(Value::Null),
        }),
    }
}

fn query_job_next_run_at(conn: &Connection, job_id: &str) -> Value {
    let has_jobs_table = conn
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'apscheduler_jobs' LIMIT 1",
            [],
            |_| Ok(()),
        )
        .is_ok();
    if !has_jobs_table {
        return Value::Null;
    }
    conn.query_row(
        "SELECT next_run_time FROM apscheduler_jobs WHERE id = ?1",
        rusqlite::params![job_id],
        |row| row.get::<_, Option<f64>>(0),
    )
    .ok()
    .flatten()
    .map(Value::from)
    .unwrap_or(Value::Null)
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
        let stats_json: String = row
            .get::<_, Option<String>>(8)?
            .unwrap_or_else(|| "{}".into());
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

pub(super) fn query_executions(schedule_id: Option<&str>, limit: i64) -> Value {
    let conn = match open_scheduler_db() {
        Some(c) => c,
        None => return json!({"executions": []}),
    };
    let (query, params): (String, Vec<Box<dyn rusqlite::types::ToSql>>) = if let Some(sid) =
        schedule_id
    {
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

pub(super) fn query_activity(limit: i64) -> Value {
    let conn = match open_scheduler_db() {
        Some(c) => c,
        None => return json!({"activities": []}),
    };
    let mut activities: Vec<Value> = Vec::new();

    if let Ok(mut stmt) = conn.prepare(
        "SELECT job_id, schedule_id, target_type, target_key, source_type, status, created_at, started_at, error \
         FROM sensor_sync_jobs WHERE status IN ('queued', 'running') ORDER BY created_at ASC LIMIT ?1",
    ) {
        let jobs = stmt
            .query_map(rusqlite::params![limit.max(1)], |row| {
                let job_id: String = row.get(0)?;
                let schedule_id: String = row.get(1)?;
                let target_type: String = row.get(2)?;
                let target_key: String = row.get(3)?;
                let source_type: String = row.get(4)?;
                let status: String = row.get(5)?;
                let created_at: Option<f64> = row.get(6)?;
                let started_at: Option<f64> = row.get(7)?;
                let error: Option<String> = row.get(8)?;
                Ok(json!({
                    "activity_id": format!("sensor_job:{job_id}"),
                    "schedule_id": schedule_id,
                    "title": source_type,
                    "target_type": target_type,
                    "target_key": target_key,
                    "status": status,
                    "planned_at": created_at,
                    "started_at": started_at,
                    "duration_ms": Value::Null,
                    "cancellable": status == "queued",
                    "cancel_kind": if status == "queued" { Value::String("sensor_sync_job".to_string()) } else { Value::Null },
                    "error": error,
                }))
            })
            .ok()
            .map(|iter| iter.filter_map(|item| item.ok()).collect::<Vec<_>>())
            .unwrap_or_default();
        activities.extend(jobs);
    }

    let schedules = query_schedules(true)
        .get("schedules")
        .and_then(|value| value.as_array())
        .cloned()
        .unwrap_or_default();
    for schedule in schedules {
        if activities.len() >= limit.max(1) as usize {
            break;
        }
        let state = schedule
            .get("target_state")
            .cloned()
            .unwrap_or_else(|| json!({}));
        let running = state
            .get("running")
            .and_then(|value| value.as_bool())
            .unwrap_or(false);
        let target_type = schedule
            .get("target_type")
            .and_then(|value| value.as_str())
            .unwrap_or("");
        let schedule_id = schedule
            .get("schedule_id")
            .and_then(|value| value.as_str())
            .unwrap_or("");
        let target_key = schedule
            .get("target_key")
            .and_then(|value| value.as_str())
            .unwrap_or("");
        let title = schedule_title(&schedule);
        if running && target_type != "sensor_sync" {
            activities.push(json!({
                "activity_id": format!("target:{target_type}:{target_key}"),
                "schedule_id": schedule_id,
                "title": title,
                "target_type": target_type,
                "target_key": target_key,
                "status": "running",
                "planned_at": Value::Null,
                "started_at": state.get("last_run_at").cloned().unwrap_or(Value::Null),
                "duration_ms": Value::Null,
                "cancellable": false,
                "cancel_kind": Value::Null,
                "error": state.get("last_error").cloned().unwrap_or(Value::Null),
            }));
            continue;
        }
        let next_run_at = state.get("next_run_at").cloned().unwrap_or(Value::Null);
        if !next_run_at.is_null() && !running {
            activities.push(json!({
                "activity_id": format!("upcoming:{schedule_id}"),
                "schedule_id": schedule_id,
                "title": title,
                "target_type": target_type,
                "target_key": target_key,
                "status": "upcoming",
                "planned_at": next_run_at,
                "started_at": Value::Null,
                "duration_ms": Value::Null,
                "cancellable": false,
                "cancel_kind": Value::Null,
                "error": state.get("last_error").cloned().unwrap_or(Value::Null),
            }));
        }
    }

    activities.truncate(limit.max(1) as usize);
    json!({"activities": activities})
}

fn schedule_title(schedule: &Value) -> String {
    schedule
        .get("metadata")
        .and_then(|metadata| metadata.get("title"))
        .and_then(|value| value.as_str())
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            schedule
                .get("target_payload")
                .and_then(|payload| payload.get("title"))
                .and_then(|value| value.as_str())
        })
        .unwrap_or_else(|| {
            schedule
                .get("target_key")
                .and_then(|value| value.as_str())
                .unwrap_or("")
        })
        .to_string()
}
