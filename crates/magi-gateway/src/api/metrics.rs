use axum::extract::Query;
use axum::Json;
use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::{json, Value};
use std::sync::Mutex;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use sysinfo::System;

use crate::db;

#[derive(Deserialize)]
pub struct SummaryQuery {
    pub days: Option<i64>,
    pub model_limit: Option<i64>,
}

#[derive(Deserialize)]
pub struct TimeseriesQuery {
    pub days: Option<i64>,
}

/// Native GET /api/metrics/llm/usage/summary handler.
pub async fn llm_usage_summary(Query(params): Query<SummaryQuery>) -> Json<Value> {
    let days = params.days.unwrap_or(7).clamp(1, 365);
    let model_limit = params.model_limit.unwrap_or(8).clamp(1, 50);
    let result = tokio::task::spawn_blocking(move || query_summary(days, model_limit))
        .await
        .unwrap_or_else(|_| empty_summary(7));
    Json(json!({
        "success": true,
        "message": "LLM usage summary loaded",
        "data": result,
    }))
}

/// Native GET /api/metrics/llm/usage/timeseries handler.
pub async fn llm_usage_timeseries(Query(params): Query<TimeseriesQuery>) -> Json<Value> {
    let days = params.days.unwrap_or(7).clamp(1, 365);
    let result = tokio::task::spawn_blocking(move || query_timeseries(days))
        .await
        .unwrap_or_else(|_| json!({"window_days": days, "points": []}));
    Json(json!({
        "success": true,
        "message": "LLM usage timeseries loaded",
        "data": result,
    }))
}

fn now_epoch() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn open_llm_usage_db() -> Option<Connection> {
    let path = db::llm_usage_db_path();
    if !path.exists() {
        return None;
    }
    Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY).ok()
}

fn empty_summary(days: i64) -> Value {
    json!({
        "window_days": days,
        "totals": {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "calls_with_usage": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "avg_latency_ms": 0.0,
            "avg_ttft_ms": null,
            "total_cost_usd": 0.0,
        },
        "providers": [],
        "models": [],
        "request_kinds": [],
    })
}

fn query_summary(days: i64, model_limit: i64) -> Value {
    let conn = match open_llm_usage_db() {
        Some(c) => c,
        None => return empty_summary(days),
    };
    let cutoff = now_epoch() - (days as f64 * 86400.0);

    // Totals
    let totals = match conn.query_row(
        "SELECT \
            COUNT(*), \
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), \
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), \
            SUM(CASE WHEN usage_available = 1 THEN 1 ELSE 0 END), \
            COALESCE(SUM(prompt_tokens), 0), \
            COALESCE(SUM(completion_tokens), 0), \
            COALESCE(SUM(total_tokens), 0), \
            COALESCE(AVG(latency_ms), 0), \
            COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0), \
            COALESCE(SUM(cost_usd), 0) \
         FROM llm_usage WHERE created_at >= ?1",
        rusqlite::params![cutoff],
        |row| {
            let avg_ttft: f64 = row.get(8)?;
            Ok(json!({
                "total_calls": row.get::<_, i64>(0)?,
                "successful_calls": row.get::<_, i64>(1)?,
                "failed_calls": row.get::<_, i64>(2)?,
                "calls_with_usage": row.get::<_, i64>(3)?,
                "prompt_tokens": row.get::<_, i64>(4)?,
                "completion_tokens": row.get::<_, i64>(5)?,
                "total_tokens": row.get::<_, i64>(6)?,
                "avg_latency_ms": (row.get::<_, f64>(7)? * 100.0).round() / 100.0,
                "avg_ttft_ms": if avg_ttft > 0.0 { json!((avg_ttft * 100.0).round() / 100.0) } else { Value::Null },
                "total_cost_usd": (row.get::<_, f64>(9)? * 10000.0).round() / 10000.0,
            }))
        },
    ) {
        Ok(v) => v,
        Err(_) => return empty_summary(days),
    };

    // Provider breakdown
    let providers = query_grouped_usage(
        &conn,
        "SELECT provider, \
            COUNT(*), \
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), \
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), \
            COALESCE(SUM(prompt_tokens), 0), \
            COALESCE(SUM(completion_tokens), 0), \
            COALESCE(SUM(total_tokens), 0), \
            COALESCE(AVG(latency_ms), 0), \
            COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0), \
            COALESCE(SUM(cost_usd), 0) \
         FROM llm_usage WHERE created_at >= ?1 \
         GROUP BY provider ORDER BY total_tokens DESC, calls DESC",
        rusqlite::params![cutoff],
        &["provider"],
    );

    // Model breakdown
    let models = query_grouped_usage(
        &conn,
        "SELECT provider, model, \
            COUNT(*), \
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), \
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), \
            COALESCE(SUM(prompt_tokens), 0), \
            COALESCE(SUM(completion_tokens), 0), \
            COALESCE(SUM(total_tokens), 0), \
            COALESCE(AVG(latency_ms), 0), \
            COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0), \
            COALESCE(SUM(cost_usd), 0) \
         FROM llm_usage WHERE created_at >= ?1 \
         GROUP BY provider, model ORDER BY total_tokens DESC, calls DESC LIMIT ?2",
        rusqlite::params![cutoff, model_limit],
        &["provider", "model"],
    );

    // Request kind breakdown
    let request_kinds = query_grouped_usage(
        &conn,
        "SELECT request_kind, \
            COUNT(*), \
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), \
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), \
            COALESCE(SUM(prompt_tokens), 0), \
            COALESCE(SUM(completion_tokens), 0), \
            COALESCE(SUM(total_tokens), 0), \
            COALESCE(AVG(latency_ms), 0), \
            COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0), \
            COALESCE(SUM(cost_usd), 0) \
         FROM llm_usage WHERE created_at >= ?1 \
         GROUP BY request_kind ORDER BY total_tokens DESC, calls DESC",
        rusqlite::params![cutoff],
        &["request_kind"],
    );

    json!({
        "window_days": days,
        "totals": totals,
        "providers": providers,
        "models": models,
        "request_kinds": request_kinds,
    })
}

/// Generic grouped usage query. `label_cols` are the leading string columns.
fn query_grouped_usage(
    conn: &Connection,
    query: &str,
    params: &[&dyn rusqlite::types::ToSql],
    label_cols: &[&str],
) -> Vec<Value> {
    let mut stmt = match conn.prepare(query) {
        Ok(s) => s,
        Err(_) => return vec![],
    };
    let n = label_cols.len();
    stmt.query_map(params, |row| {
        let mut obj = serde_json::Map::new();
        for (i, col) in label_cols.iter().enumerate() {
            obj.insert(
                col.to_string(),
                json!(row.get::<_, String>(i)?),
            );
        }
        let avg_ttft: f64 = row.get(n + 7)?;
        obj.insert("calls".into(), json!(row.get::<_, i64>(n)?));
        obj.insert("successful_calls".into(), json!(row.get::<_, i64>(n + 1)?));
        obj.insert("failed_calls".into(), json!(row.get::<_, i64>(n + 2)?));
        obj.insert("prompt_tokens".into(), json!(row.get::<_, i64>(n + 3)?));
        obj.insert("completion_tokens".into(), json!(row.get::<_, i64>(n + 4)?));
        obj.insert("total_tokens".into(), json!(row.get::<_, i64>(n + 5)?));
        obj.insert(
            "avg_latency_ms".into(),
            json!((row.get::<_, f64>(n + 6)? * 100.0).round() / 100.0),
        );
        obj.insert(
            "avg_ttft_ms".into(),
            if avg_ttft > 0.0 {
                json!((avg_ttft * 100.0).round() / 100.0)
            } else {
                json!(0.0)
            },
        );
        obj.insert(
            "cost_usd".into(),
            json!((row.get::<_, f64>(n + 8)? * 10000.0).round() / 10000.0),
        );
        Ok(Value::Object(obj))
    })
    .ok()
    .map(|iter| iter.filter_map(|r| r.ok()).collect())
    .unwrap_or_default()
}

fn query_timeseries(days: i64) -> Value {
    let conn = match open_llm_usage_db() {
        Some(c) => c,
        None => return json!({"window_days": days, "points": []}),
    };
    let cutoff = now_epoch() - (days as f64 * 86400.0);
    let mut stmt = match conn.prepare(
        "SELECT \
            strftime('%Y-%m-%d', datetime(created_at, 'unixepoch', 'localtime')) AS day, \
            COUNT(*), \
            COALESCE(SUM(prompt_tokens), 0), \
            COALESCE(SUM(completion_tokens), 0), \
            COALESCE(SUM(total_tokens), 0), \
            COALESCE(SUM(cost_usd), 0) \
         FROM llm_usage WHERE created_at >= ?1 \
         GROUP BY day ORDER BY day ASC",
    ) {
        Ok(s) => s,
        Err(_) => return json!({"window_days": days, "points": []}),
    };
    let points: Vec<Value> = stmt
        .query_map(rusqlite::params![cutoff], |row| {
            Ok(json!({
                "day": row.get::<_, String>(0)?,
                "calls": row.get::<_, i64>(1)?,
                "prompt_tokens": row.get::<_, i64>(2)?,
                "completion_tokens": row.get::<_, i64>(3)?,
                "total_tokens": row.get::<_, i64>(4)?,
                "cost_usd": (row.get::<_, f64>(5)? * 10000.0).round() / 10000.0,
            }))
        })
        .ok()
        .map(|iter| iter.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();
    json!({
        "window_days": days,
        "points": points,
    })
}

// ---------------------------------------------------------------------------
// Runtime Overview
// ---------------------------------------------------------------------------

const HEARTBEAT_ROLE: &str = "ipc_worker";
const HEARTBEAT_STALE_AFTER_MS: i64 = 15_000;
const PENDING_COMMAND_WARNING_THRESHOLD: i64 = 100;
const MODEL_EXECUTION_WINDOW_SECS: f64 = 3600.0;

/// Native GET /api/metrics/runtime/overview handler.
pub async fn runtime_overview() -> Json<Value> {
    let result = tokio::task::spawn_blocking(build_runtime_overview)
        .await
        .unwrap_or_else(|_| empty_runtime_overview());
    Json(json!({
        "success": true,
        "message": "Runtime overview loaded",
        "data": result,
    }))
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

fn empty_runtime_overview() -> Value {
    json!({
        "captured_at_ms": now_ms(),
        "system": { "cpu_percent": 0.0, "memory_percent": 0.0, "memory_used_gb": 0.0, "memory_total_gb": 0.0 },
        "runtime": { "status": "offline", "runtime_ready": false, "runtime_status": "offline", "runtime_heartbeat_age_ms": null, "queue_backlog_healthy": null, "pending_commands": null },
        "model_execution": { "avg_ttft_ms": null, "ttft_available": false, "core_model_success_rate": null, "core_model_success_rate_available": false, "intent_success_rate": null, "intent_success_rate_available": false },
        "memory": empty_memory_section(),
        "scheduler": empty_scheduler_section(),
    })
}

fn build_runtime_overview() -> Value {
    let system_metrics = build_system_metrics();
    let runtime = build_runtime_status();
    let model_execution = build_model_execution();
    let memory = build_memory_section();
    let scheduler = build_scheduler_section();

    json!({
        "captured_at_ms": now_ms(),
        "system": system_metrics,
        "runtime": runtime,
        "model_execution": model_execution,
        "memory": memory,
        "scheduler": scheduler,
    })
}

fn build_system_metrics() -> Value {
    // Keep a persistent System instance + cached snapshot so we never
    // pay the full sysinfo initialisation cost on the request path.
    // The cache is refreshed at most once per REFRESH_INTERVAL.
    static STATE: std::sync::LazyLock<Mutex<SysMetricsCache>> =
        std::sync::LazyLock::new(|| Mutex::new(SysMetricsCache::new()));

    const REFRESH_INTERVAL: std::time::Duration = std::time::Duration::from_secs(2);

    let mut cache = STATE.lock().unwrap_or_else(|e| e.into_inner());
    if cache.last_refresh.elapsed() >= REFRESH_INTERVAL {
        cache.refresh();
    }
    cache.snapshot.clone()
}

struct SysMetricsCache {
    sys: System,
    snapshot: Value,
    last_refresh: Instant,
}

impl SysMetricsCache {
    fn new() -> Self {
        let mut sys = System::new();
        sys.refresh_memory();
        sys.refresh_cpu_usage();
        let snapshot = Self::build_snapshot(&sys);
        Self {
            sys,
            snapshot,
            last_refresh: Instant::now(),
        }
    }

    fn refresh(&mut self) {
        self.sys.refresh_memory();
        self.sys.refresh_cpu_usage();
        self.snapshot = Self::build_snapshot(&self.sys);
        self.last_refresh = Instant::now();
    }

    fn build_snapshot(sys: &System) -> Value {
        let cpu_percent = sys.global_cpu_usage() as f64;
        let total_mem = sys.total_memory() as f64;
        let used_mem = sys.used_memory() as f64;
        let memory_percent = if total_mem > 0.0 {
            (used_mem / total_mem) * 100.0
        } else {
            0.0
        };
        let gb = 1024.0 * 1024.0 * 1024.0;

        json!({
            "cpu_percent": (cpu_percent * 10.0).round() / 10.0,
            "memory_percent": (memory_percent * 10.0).round() / 10.0,
            "memory_used_gb": (used_mem / gb * 100.0).round() / 100.0,
            "memory_total_gb": (total_mem / gb * 100.0).round() / 100.0,
        })
    }
}

fn build_runtime_status() -> Value {
    let db_path = db::runtime_trace_db_path();
    if !db_path.exists() {
        return json!({
            "status": "offline", "runtime_ready": false, "runtime_status": "offline",
            "runtime_heartbeat_age_ms": null, "queue_backlog_healthy": null, "pending_commands": null,
        });
    }

    let conn = match db::open_readonly(&db_path) {
        Some(c) => c,
        None => {
            return json!({
                "status": "offline", "runtime_ready": false, "runtime_status": "offline",
                "runtime_heartbeat_age_ms": null, "queue_backlog_healthy": null, "pending_commands": null,
            });
        }
    };

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
            let age_ms = (now_ms() - last_seen_at_ms).max(0);
            if age_ms > HEARTBEAT_STALE_AFTER_MS {
                (false, "stale".to_string(), Some(age_ms), Some(backlog))
            } else {
                let ready = status == "ready";
                (ready, status, Some(age_ms), Some(backlog))
            }
        }
        Err(_) => (false, "offline".to_string(), None, None),
    };

    let pending_commands: Option<i64> = conn
        .query_row(
            "SELECT COUNT(*) FROM runtime_notifications WHERE consumed_at IS NULL",
            [],
            |row| row.get(0),
        )
        .ok();

    let queue_backlog_healthy = queue_backlog
        .map(|b| b <= PENDING_COMMAND_WARNING_THRESHOLD);

    let status = if runtime_ready && queue_backlog_healthy.unwrap_or(true) {
        "ready"
    } else if runtime_ready {
        "degraded"
    } else {
        &runtime_status
    };

    json!({
        "status": status,
        "runtime_ready": runtime_ready,
        "runtime_status": runtime_status,
        "runtime_heartbeat_age_ms": heartbeat_age_ms,
        "queue_backlog_healthy": queue_backlog_healthy,
        "pending_commands": pending_commands,
    })
}

fn build_model_execution() -> Value {
    let conn = match open_llm_usage_db() {
        Some(c) => c,
        None => {
            return json!({
                "avg_ttft_ms": null, "ttft_available": false,
                "core_model_success_rate": null, "core_model_success_rate_available": false,
                "intent_success_rate": null, "intent_success_rate_available": false,
            });
        }
    };

    let cutoff = now_epoch() - MODEL_EXECUTION_WINDOW_SECS;

    // Average TTFT in recent window
    let (avg_ttft, ttft_available) = conn
        .query_row(
            "SELECT AVG(ttft_ms), COUNT(*) FROM llm_usage WHERE created_at >= ?1 AND ttft_ms > 0",
            rusqlite::params![cutoff],
            |row| Ok((row.get::<_, Option<f64>>(0)?, row.get::<_, i64>(1)?)),
        )
        .map(|(avg, count)| {
            if count > 0 {
                (avg.map(|v| (v * 10.0).round() / 10.0), true)
            } else {
                (None, false)
            }
        })
        .unwrap_or((None, false));

    // Core model (chat) success rate
    let (core_rate, core_available) = compute_success_rate(&conn, cutoff, "chat");

    // Intent success rate
    let (intent_rate, intent_available) = compute_success_rate(&conn, cutoff, "intent");

    json!({
        "avg_ttft_ms": avg_ttft,
        "ttft_available": ttft_available,
        "core_model_success_rate": core_rate,
        "core_model_success_rate_available": core_available,
        "intent_success_rate": intent_rate,
        "intent_success_rate_available": intent_available,
    })
}

fn compute_success_rate(conn: &Connection, cutoff: f64, request_kind: &str) -> (Option<f64>, bool) {
    conn.query_row(
        "SELECT SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), COUNT(*) FROM llm_usage WHERE created_at >= ?1 AND request_kind = ?2",
        rusqlite::params![cutoff, request_kind],
        |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?)),
    )
    .map(|(success, total)| {
        if total > 0 {
            let rate = (success as f64 / total as f64) * 100.0;
            (Some((rate * 10.0).round() / 10.0), true)
        } else {
            (None, false)
        }
    })
    .unwrap_or((None, false))
}

fn empty_memory_section() -> Value {
    let empty_layer = json!({"pending": 0, "worker_running": false, "vector_enabled": false, "async_embeddings": false});
    json!({
        "total_pending": 0,
        "l2": { "is_running": false, "extract_pending": 0, "reconcile_pending": 0, "snapshot_pending": 0, "total_pending": 0 },
        "embeddings": { "total_pending": 0, "l1": empty_layer, "l3": empty_layer, "l4": empty_layer },
    })
}

fn build_memory_section() -> Value {
    // L2 pending from memory.db
    let (l2_extract, l2_reconcile, l2_snapshot) = match db::open_readonly(&db::memory_db_path()) {
        Some(conn) => {
            let rows = db::query_to_json_array(
                &conn,
                "SELECT status, COUNT(*) AS cnt FROM l2_projection_jobs GROUP BY status",
                &[],
            );
            let mut pending: i64 = 0;
            let mut claimed: i64 = 0;
            for row in &rows {
                let s = row.get("status").and_then(|v| v.as_str()).unwrap_or("");
                let n = row.get("cnt").and_then(|v| v.as_i64()).unwrap_or(0);
                match s {
                    "pending" => pending = n,
                    "claimed" => claimed = n,
                    _ => {}
                }
            }
            (pending + claimed, 0i64, 0i64)
        }
        None => (0, 0, 0),
    };
    let l2_total = l2_extract + l2_reconcile + l2_snapshot;

    // Embedding pending per layer
    let l1 = embedding_pending(&db::l1_events_db_path(), "fact_events");
    let l3 = embedding_pending(&db::memory_db_path(), "summaries");
    let l4 = embedding_pending(&db::memory_db_path(), "procedural_skills");

    let l1_p = l1.get("pending").and_then(|v| v.as_i64()).unwrap_or(0);
    let l3_p = l3.get("pending").and_then(|v| v.as_i64()).unwrap_or(0);
    let l4_p = l4.get("pending").and_then(|v| v.as_i64()).unwrap_or(0);
    let embed_total = l1_p + l3_p + l4_p;

    json!({
        "total_pending": l2_total + embed_total,
        "l2": {
            "is_running": false,
            "extract_pending": l2_extract,
            "reconcile_pending": l2_reconcile,
            "snapshot_pending": l2_snapshot,
            "total_pending": l2_total,
        },
        "embeddings": {
            "total_pending": embed_total,
            "l1": l1,
            "l3": l3,
            "l4": l4,
        },
    })
}

fn embedding_pending(db_path: &std::path::Path, table: &str) -> Value {
    if let Some(conn) = db::open_readonly(db_path) {
        let sql = format!(
            "SELECT COUNT(*) FROM {} WHERE embedding_status = 'pending'",
            table
        );
        let pending = db::count_rows(&conn, &sql, &[]);
        return json!({
            "pending": pending,
            "worker_running": false,
            "vector_enabled": false,
            "async_embeddings": false,
        });
    }
    json!({"pending": 0, "worker_running": false, "vector_enabled": false, "async_embeddings": false})
}

fn empty_scheduler_section() -> Value {
    json!({
        "enabled_schedule_count": 0,
        "running_target_count": 0,
        "errored_target_count": 0,
        "upcoming_target_count": 0,
        "recent_targets": [],
    })
}

fn build_scheduler_section() -> Value {
    let conn = match db::open_readonly(&db::scheduler_db_path()) {
        Some(c) => c,
        None => return empty_scheduler_section(),
    };

    let enabled_count = db::count_rows(&conn, "SELECT COUNT(*) FROM schedules WHERE enabled = 1", &[]);

    let running_count = db::count_rows(&conn, "SELECT COUNT(*) FROM target_state WHERE running = 1", &[]);

    let errored_count = db::count_rows(
        &conn,
        "SELECT COUNT(*) FROM target_state WHERE last_error IS NOT NULL AND last_error != ''",
        &[],
    );

    let upcoming_count = db::count_rows(
        &conn,
        "SELECT COUNT(*) FROM target_state WHERE next_run_at IS NOT NULL AND running = 0",
        &[],
    );

    let recent_targets = db::query_to_json_array(
        &conn,
        "SELECT target_type, target_key, running, last_error, next_run_at, updated_at \
         FROM target_state ORDER BY updated_at DESC LIMIT 5",
        &[],
    )
    .into_iter()
    .map(|row| {
        json!({
            "target_type": row.get("target_type").cloned().unwrap_or(Value::Null),
            "target_key": row.get("target_key").cloned().unwrap_or(Value::Null),
            "running": row.get("running").and_then(|v| v.as_i64()).map(|v| v != 0).unwrap_or(false),
            "last_error": row.get("last_error").cloned().unwrap_or(Value::Null),
            "next_run_at": row.get("next_run_at").cloned().unwrap_or(Value::Null),
            "updated_at": row.get("updated_at").cloned().unwrap_or(Value::Null),
        })
    })
    .collect::<Vec<_>>();

    json!({
        "enabled_schedule_count": enabled_count,
        "running_target_count": running_count,
        "errored_target_count": errored_count,
        "upcoming_target_count": upcoming_count,
        "recent_targets": recent_targets,
    })
}
