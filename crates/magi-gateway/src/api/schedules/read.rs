use rusqlite::Connection;
use serde_json::{json, Value};

use super::storage::{open_scheduler_db, serialize_schedule, SCHEDULE_COLUMNS};
use super::types::ActivityFilters;

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

pub(super) fn query_activity(filters: ActivityFilters) -> Value {
    let conn = match open_scheduler_db() {
        Some(c) => c,
        None => return json!({"activities": [], "total": 0}),
    };
    let limit = filters.limit.max(1);
    let offset = filters.offset.max(0);
    let mut activities: Vec<Value> = Vec::new();
    let live_only_on_first_page = offset == 0;

    // Build a schedule_id → title lookup once. We need this both for the
    // currently-running snapshots and for naming history rows (so the user
    // sees "screen_time" instead of "exec_<hex>"). Includes disabled
    // schedules so history for paused schedules still shows their name.
    let schedules = query_schedules(false)
        .get("schedules")
        .and_then(|value| value.as_array())
        .cloned()
        .unwrap_or_default();
    let mut schedule_titles: std::collections::HashMap<String, String> =
        std::collections::HashMap::with_capacity(schedules.len());
    for schedule in &schedules {
        if let Some(id) = schedule.get("schedule_id").and_then(|v| v.as_str()) {
            schedule_titles.insert(id.to_string(), schedule_title(schedule));
        }
    }

    // 1) Outstanding sensor sync jobs (queued/running) — first page only.
    if live_only_on_first_page {
        if let Ok(mut stmt) = conn.prepare(
        "SELECT job_id, schedule_id, target_type, target_key, source_type, status, created_at, started_at, error \
         FROM sensor_sync_jobs WHERE status IN ('queued', 'running') ORDER BY created_at ASC LIMIT ?1",
    ) {
        let jobs = stmt
            .query_map(rusqlite::params![limit], |row| {
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
                    "finished_at": Value::Null,
                    "duration_ms": Value::Null,
                    "cancellable": status == "queued",
                    "cancel_kind": if status == "queued" { Value::String("sensor_sync_job".to_string()) } else { Value::Null },
                    "error": error,
                    "background_task_id": Value::Null,
                    "result_message": Value::Null,
                    "stats": json!({}),
                    "manual": false,
                }))
            })
            .ok()
            .map(|iter| iter.filter_map(|item| item.ok()).collect::<Vec<_>>())
            .unwrap_or_default();
        activities.extend(jobs);
    }
    } // end live_only_on_first_page (sensor jobs)

    // 2) Currently running non-sensor schedules — first page only.
    // Upcoming (next_run_at) snapshots are intentionally NOT surfaced — the
    // schedule config page already shows "next run" per row, and upcoming rows
    // have no actions to take, so they'd just be duplicate noise.
    if live_only_on_first_page {
        for schedule in &schedules {
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
            if !running || target_type == "sensor_sync" {
                continue;
            }
            let schedule_id = schedule
                .get("schedule_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let target_key = schedule
                .get("target_key")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let title = schedule_title(schedule);
            activities.push(json!({
                "activity_id": format!("target:{target_type}:{target_key}"),
                "schedule_id": schedule_id,
                "title": title,
                "target_type": target_type,
                "target_key": target_key,
                "status": "running",
                "planned_at": Value::Null,
                "started_at": state.get("last_run_at").cloned().unwrap_or(Value::Null),
                "finished_at": Value::Null,
                "duration_ms": Value::Null,
                "cancellable": false,
                "cancel_kind": Value::Null,
                "error": state.get("last_error").cloned().unwrap_or(Value::Null),
                "background_task_id": Value::Null,
                "result_message": Value::Null,
                "stats": json!({}),
                "manual": false,
            }));
        }
    } // end live_only_on_first_page (running snapshots)

    // 3) Historical executions from schedule_executions, scoped to the
    // requested window + filters.
    // Map display-status names back to DB names: succeeded → success.
    let raw_statuses: Vec<String> = filters
        .statuses
        .iter()
        .map(|s| match s.as_str() {
            "succeeded" => "success".to_string(),
            other => other.to_string(),
        })
        .collect();
    let mut where_clauses: Vec<String> = Vec::new();
    let mut params: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
    if let Some(since) = filters.since {
        where_clauses.push(format!("started_at >= ?{}", params.len() + 1));
        params.push(Box::new(since));
    }
    if let Some(until) = filters.until {
        where_clauses.push(format!("started_at <= ?{}", params.len() + 1));
        params.push(Box::new(until));
    }
    if !raw_statuses.is_empty() {
        let placeholders: Vec<String> = (0..raw_statuses.len())
            .map(|i| format!("?{}", params.len() + 1 + i))
            .collect();
        where_clauses.push(format!("status IN ({})", placeholders.join(",")));
        for s in &raw_statuses {
            params.push(Box::new(s.clone()));
        }
    }
    if !filters.target_types.is_empty() {
        let placeholders: Vec<String> = (0..filters.target_types.len())
            .map(|i| format!("?{}", params.len() + 1 + i))
            .collect();
        where_clauses.push(format!("target_type IN ({})", placeholders.join(",")));
        for t in &filters.target_types {
            params.push(Box::new(t.clone()));
        }
    }
    let where_sql = if where_clauses.is_empty() {
        String::new()
    } else {
        format!(" WHERE {}", where_clauses.join(" AND "))
    };

    // Count of history rows matching filters (used for frontend pagination).
    // Uses the same params as the data query so far, before we append
    // LIMIT/OFFSET below.
    let count_query = format!("SELECT COUNT(*) FROM schedule_executions{where_sql}");
    let history_total: i64 = {
        let param_refs: Vec<&dyn rusqlite::types::ToSql> =
            params.iter().map(|p| p.as_ref()).collect();
        conn.query_row(&count_query, param_refs.as_slice(), |row| {
            row.get::<_, i64>(0)
        })
        .unwrap_or(0)
    };

    let limit_param_idx = params.len() + 1;
    params.push(Box::new(limit));
    let offset_param_idx = params.len() + 1;
    params.push(Box::new(offset));
    let history_query = format!(
        "SELECT {EXECUTION_COLUMNS} FROM schedule_executions{where_sql} \
         ORDER BY started_at DESC LIMIT ?{limit_param_idx} OFFSET ?{offset_param_idx}"
    );

    if let Ok(mut stmt) = conn.prepare(&history_query) {
        let param_refs: Vec<&dyn rusqlite::types::ToSql> =
            params.iter().map(|p| p.as_ref()).collect();
        let rows: Vec<Value> = stmt
            .query_map(param_refs.as_slice(), serialize_execution)
            .ok()
            .map(|iter| iter.filter_map(|r| r.ok()).collect())
            .unwrap_or_default();
        for mut row in rows {
            // Adapt the execution row into the activity DTO shape used elsewhere.
            let execution_id = row
                .get("execution_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let schedule_id = row
                .get("schedule_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let raw_status = row
                .get("status")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let display_status = match raw_status.as_str() {
                "success" => "succeeded",
                other => other,
            };
            // Use the schedule's display title so users see e.g. "screen_time"
            // or "Drink water reminder" instead of "exec_<hex>". Fall back to
            // schedule_id (more meaningful than the random execution_id) when
            // the schedule was deleted.
            let display_title = schedule_titles
                .get(&schedule_id)
                .cloned()
                .unwrap_or_else(|| schedule_id.clone());
            let object = row
                .as_object_mut()
                .expect("serialize_execution always returns object");
            object.insert(
                "activity_id".into(),
                Value::String(format!("execution:{execution_id}")),
            );
            object.insert("status".into(), Value::String(display_status.into()));
            object.insert(
                "planned_at".into(),
                object.get("started_at").cloned().unwrap_or(Value::Null),
            );
            object.insert("cancellable".into(), Value::Bool(false));
            object.insert("cancel_kind".into(), Value::Null);
            object.insert("background_task_id".into(), Value::Null);
            object.insert("title".into(), Value::String(display_title));
            activities.push(row);
        }
    }

    // 4) Apply the target_types / statuses filters across the merged set so
    // sensor jobs and currently-running rows respect them too.
    let allowed_types: Option<std::collections::HashSet<&str>> = if filters.target_types.is_empty()
    {
        None
    } else {
        Some(filters.target_types.iter().map(|s| s.as_str()).collect())
    };
    let allowed_statuses: Option<std::collections::HashSet<&str>> = if filters.statuses.is_empty() {
        None
    } else {
        Some(filters.statuses.iter().map(|s| s.as_str()).collect())
    };
    if allowed_types.is_some() || allowed_statuses.is_some() {
        activities.retain(|a| {
            let t = a.get("target_type").and_then(|v| v.as_str()).unwrap_or("");
            let s = a.get("status").and_then(|v| v.as_str()).unwrap_or("");
            allowed_types.as_ref().is_none_or(|set| set.contains(t))
                && allowed_statuses.as_ref().is_none_or(|set| set.contains(s))
        });
    }

    // 5) Sort: running first, then by started_at descending.
    activities.sort_by(|a, b| {
        let a_running = a.get("status").and_then(|v| v.as_str()) == Some("running");
        let b_running = b.get("status").and_then(|v| v.as_str()) == Some("running");
        if a_running != b_running {
            return b_running.cmp(&a_running);
        }
        let a_ts = a.get("started_at").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let b_ts = b.get("started_at").and_then(|v| v.as_f64()).unwrap_or(0.0);
        b_ts.partial_cmp(&a_ts).unwrap_or(std::cmp::Ordering::Equal)
    });

    // Truncate only when live rows pushed us past the page size on page 1;
    // on later pages the SQL LIMIT already constrained the slice.
    activities.truncate(limit as usize + 32);

    // Build chip-count aggregations. These reflect the time window only
    // (since/until), independent of the category/status filters — otherwise
    // selecting one chip would zero out every other chip and make the filter
    // unusable.
    let mut target_type_counts: std::collections::BTreeMap<String, i64> =
        std::collections::BTreeMap::new();
    let mut status_counts: std::collections::BTreeMap<String, i64> =
        std::collections::BTreeMap::new();

    // Time-window-only WHERE clause for the history aggregation.
    let mut count_where: Vec<String> = Vec::new();
    let mut count_params: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
    if let Some(since) = filters.since {
        count_where.push(format!("started_at >= ?{}", count_params.len() + 1));
        count_params.push(Box::new(since));
    }
    if let Some(until) = filters.until {
        count_where.push(format!("started_at <= ?{}", count_params.len() + 1));
        count_params.push(Box::new(until));
    }
    let count_where_sql = if count_where.is_empty() {
        String::new()
    } else {
        format!(" WHERE {}", count_where.join(" AND "))
    };
    let agg_query = format!(
        "SELECT target_type, status, COUNT(*) FROM schedule_executions{count_where_sql} \
         GROUP BY target_type, status"
    );
    if let Ok(mut stmt) = conn.prepare(&agg_query) {
        let param_refs: Vec<&dyn rusqlite::types::ToSql> =
            count_params.iter().map(|p| p.as_ref()).collect();
        let rows = stmt.query_map(param_refs.as_slice(), |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
            ))
        });
        if let Ok(rows) = rows {
            for entry in rows.flatten() {
                let (target_type, raw_status, count) = entry;
                let display_status = match raw_status.as_str() {
                    "success" => "succeeded".to_string(),
                    other => other.to_string(),
                };
                *target_type_counts.entry(target_type).or_insert(0) += count;
                *status_counts.entry(display_status).or_insert(0) += count;
            }
        }
    }

    // Live rows: count current sensor jobs (queued/running) and currently-
    // running non-sensor schedules. These are state snapshots, not time-bound,
    // so they always count regardless of the time window.
    if let Ok(mut stmt) = conn.prepare(
        "SELECT target_type, status, COUNT(*) FROM sensor_sync_jobs \
         WHERE status IN ('queued', 'running') GROUP BY target_type, status",
    ) {
        let rows = stmt.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
            ))
        });
        if let Ok(rows) = rows {
            for (target_type, status, count) in rows.flatten() {
                *target_type_counts.entry(target_type).or_insert(0) += count;
                *status_counts.entry(status).or_insert(0) += count;
            }
        }
    }
    for schedule in &schedules {
        let running = schedule
            .get("target_state")
            .and_then(|s| s.get("running"))
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        let target_type = schedule
            .get("target_type")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if running && target_type != "sensor_sync" {
            *target_type_counts
                .entry(target_type.to_string())
                .or_insert(0) += 1;
            *status_counts.entry("running".into()).or_insert(0) += 1;
        }
    }

    json!({
        "activities": activities,
        "total": history_total,
        "target_type_counts": target_type_counts,
        "status_counts": status_counts,
    })
}

fn schedule_title(schedule: &Value) -> String {
    // Match the Python `_schedule_title` precedence used everywhere else:
    // metadata/payload display_name → title → source_type → plugin_id, finally
    // fall back to schedule_id (more meaningful than target_key for users).
    for key in ["display_name", "title", "source_type", "plugin_id"] {
        for source in ["metadata", "target_payload"] {
            if let Some(value) = schedule
                .get(source)
                .and_then(|outer| outer.get(key))
                .and_then(|v| v.as_str())
                .filter(|v| !v.trim().is_empty())
            {
                return value.to_string();
            }
        }
    }
    schedule
        .get("schedule_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string()
}
