// Runtime Overview
// ---------------------------------------------------------------------------

use axum::{extract::State, Json};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use sysinfo::System;

use crate::api::memory::read_l2_projection_backlog;
use crate::api::state::ApiState;
use crate::db;

const RUNTIME_READY_IPC_TIMEOUT_MS: u64 = 1_000;
const MODEL_EXECUTION_WINDOW_SECS: f64 = 3600.0;

/// Native GET /api/metrics/runtime/overview handler.
pub async fn runtime_overview(State(state): State<ApiState>) -> Json<Value> {
    let runtime_status = load_runtime_status(&state).await;
    let result = tokio::task::spawn_blocking(move || build_runtime_overview(runtime_status))
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

fn empty_runtime_overview() -> Value {
    json!({
        "captured_at_ms": now_ms(),
        "system": { "cpu_percent": 0.0, "memory_percent": 0.0, "memory_used_gb": 0.0, "memory_total_gb": 0.0 },
        "runtime": { "status": "offline", "runtime_ready": false, "runtime_status": "offline", "queue_backlog_healthy": null, "pending_commands": null },
        "model_execution": { "avg_ttft_ms": null, "ttft_available": false, "core_model_success_rate": null, "core_model_success_rate_available": false },
        "memory": empty_memory_section(),
        "scheduler": empty_scheduler_section(),
    })
}

async fn load_runtime_status(state: &ApiState) -> Value {
    let timeout = Duration::from_millis(RUNTIME_READY_IPC_TIMEOUT_MS);
    match state
        .ipc_client
        .request_with_timeout("runtime.ready", None, timeout)
        .await
    {
        Ok(value) => runtime_status_from_ready_payload(value),
        Err(_) => json!({
            "status": "degraded",
            "runtime_ready": false,
            "runtime_status": "unresponsive",
            "queue_backlog_healthy": null,
            "pending_commands": null,
        }),
    }
}

fn runtime_status_from_ready_payload(value: Value) -> Value {
    let data = value.get("data").unwrap_or(&Value::Null);
    json!({
        "status": data.get("status").cloned().unwrap_or_else(|| Value::String("degraded".into())),
        "runtime_ready": data.get("runtime_ready").cloned().unwrap_or(Value::Bool(false)),
        "runtime_status": data.get("runtime_status").cloned().unwrap_or_else(|| Value::String("offline".into())),
        "queue_backlog_healthy": data.get("queue_backlog_healthy").cloned().unwrap_or(Value::Null),
        "pending_commands": data.get("pending_commands").cloned().unwrap_or(Value::Null),
    })
}

fn build_runtime_overview(runtime_status: Value) -> Value {
    let system_metrics = build_system_metrics();
    let model_execution = build_model_execution();
    let memory = build_memory_section();
    let scheduler = build_scheduler_section();

    json!({
        "captured_at_ms": now_ms(),
        "system": system_metrics,
        "runtime": runtime_status,
        "model_execution": model_execution,
        "memory": memory,
        "scheduler": scheduler,
    })
}

fn build_system_metrics() -> Value {
    // Keep a persistent System instance + cached snapshot so we never
    // pay the full sysinfo initialisation cost on the request path.
    // The cache is refreshed at most once per REFRESH_INTERVAL.
    // Eagerly initialised at startup via warm_sysinfo_cache().
    static STATE: std::sync::LazyLock<Mutex<SysMetricsCache>> =
        std::sync::LazyLock::new(|| Mutex::new(SysMetricsCache::new()));

    const REFRESH_INTERVAL: std::time::Duration = std::time::Duration::from_secs(2);

    let mut cache = STATE.lock().unwrap_or_else(|e| e.into_inner());
    if cache.last_refresh.elapsed() >= REFRESH_INTERVAL {
        cache.refresh();
    }
    cache.snapshot.clone()
}

/// Force-initialise the sysinfo cache on a background thread so the
/// first request never pays the ~4 s macOS IOKit startup cost.
/// Call once at server startup (non-blocking — spawns its own thread).
pub fn warm_sysinfo_cache() {
    std::thread::spawn(|| {
        let _ = build_system_metrics();
    });
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

fn build_model_execution() -> Value {
    let conn = match open_llm_usage_db() {
        Some(c) => c,
        None => {
            return json!({
                "avg_ttft_ms": null, "ttft_available": false,
                "core_model_success_rate": null, "core_model_success_rate_available": false,
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

    json!({
        "avg_ttft_ms": avg_ttft,
        "ttft_available": ttft_available,
        "core_model_success_rate": core_rate,
        "core_model_success_rate_available": core_available,
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
    let l2_projection_backlog = db::open_readonly(&db::memory_db_path())
        .map(|conn| read_l2_projection_backlog(&conn))
        .unwrap_or_default();
    let (l2_extract, l2_reconcile, l2_snapshot) =
        (l2_projection_backlog.pending_work(), 0i64, 0i64);
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
            "is_running": l2_projection_backlog.running > 0,
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

    let enabled_count = db::count_rows(
        &conn,
        "SELECT COUNT(*) FROM schedules WHERE enabled = 1",
        &[],
    );

    let running_count = db::count_rows(
        &conn,
        "SELECT COUNT(*) FROM target_state WHERE running = 1",
        &[],
    );

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

#[cfg(test)]
mod tests {
    use super::build_memory_section;
    use crate::db;
    use rusqlite::Connection;
    use std::path::PathBuf;
    use std::sync::MutexGuard;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct IsolatedMagiBase {
        previous_base_dir: Option<PathBuf>,
        root: PathBuf,
        _lock: MutexGuard<'static, ()>,
    }

    impl Drop for IsolatedMagiBase {
        fn drop(&mut self) {
            db::set_magi_base_dir_override_for_tests(self.previous_base_dir.take());
            let _ = std::fs::remove_dir_all(&self.root);
        }
    }

    fn isolated_magi_base(label: &str) -> IsolatedMagiBase {
        let lock = db::magi_base_dir_override_test_lock();
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "magi-gateway-runtime-{label}-{}-{nonce}",
            std::process::id()
        ));
        let magi_base = root.join(".magi");
        std::fs::create_dir_all(magi_base.join("data").join("memory")).expect("create memory dir");
        let previous_base_dir = db::set_magi_base_dir_override_for_tests(Some(magi_base));
        IsolatedMagiBase {
            previous_base_dir,
            root,
            _lock: lock,
        }
    }

    fn seed_memory_databases(statuses: &[&str]) {
        let memory_conn = Connection::open(db::memory_db_path()).expect("open memory db");
        memory_conn
            .execute_batch(
                "CREATE TABLE l2_projection_jobs(status TEXT NOT NULL);
                 CREATE TABLE summaries(embedding_status TEXT);
                 CREATE TABLE procedural_skills(embedding_status TEXT);",
            )
            .expect("create memory tables");
        for status in statuses {
            memory_conn
                .execute(
                    "INSERT INTO l2_projection_jobs(status) VALUES (?1)",
                    [status],
                )
                .expect("insert projection job");
        }

        let l1_conn = Connection::open(db::l1_events_db_path()).expect("open l1 db");
        l1_conn
            .execute_batch("CREATE TABLE fact_events(embedding_status TEXT);")
            .expect("create l1 tables");
    }

    #[test]
    fn memory_section_counts_queued_and_running_l2_projection_jobs() {
        let _base = isolated_magi_base("queued-running-l2");
        seed_memory_databases(&[
            "pending", "queued", "queued", "running", "running", "running",
        ]);

        let section = build_memory_section();

        assert_eq!(section["l2"]["extract_pending"], 6);
        assert_eq!(section["l2"]["total_pending"], 6);
        assert_eq!(section["total_pending"], 6);
        assert_eq!(section["l2"]["is_running"], true);
    }
}
