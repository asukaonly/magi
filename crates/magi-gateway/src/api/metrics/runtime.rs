//! Combine native process metrics with data-owner diagnostics over IPC.
use crate::api::state::ApiState;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use sysinfo::System;

pub async fn runtime_overview(State(state): State<ApiState>) -> Response {
    let (runtime, business) = tokio::join!(
        load_runtime_status(&state),
        state
            .ipc_client
            .request_with_timeout("runtime.metrics", None, Duration::from_secs(3))
    );
    let business = business
        .ok()
        .and_then(|value| serde_json::from_value::<BusinessMetrics>(value).ok())
        .unwrap_or_default();
    let system = match tokio::task::spawn_blocking(build_system_metrics).await {
        Ok(value) => value,
        Err(_) => {
            return (
                StatusCode::SERVICE_UNAVAILABLE,
                "System metrics are unavailable",
            )
                .into_response()
        }
    };
    Json(
        json!({"success": true, "message": "Runtime overview loaded", "data": {
            "captured_at_ms": SystemTime::now().duration_since(UNIX_EPOCH).map(|v| v.as_millis() as u64).unwrap_or(0),
            "system": system, "runtime": runtime,
            "model_execution": business.model_execution,
            "memory": business.memory,
            "scheduler": business.scheduler,
        }}),
    ).into_response()
}

async fn load_runtime_status(state: &ApiState) -> Value {
    runtime_status_from_ready_payload(crate::api::ready::load_readiness(state).await)
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

#[derive(Default, Deserialize, Serialize)]
struct BusinessMetrics {
    model_execution: Option<ModelExecution>,
    memory: Option<MemoryMetrics>,
    scheduler: Option<SchedulerMetrics>,
}
#[derive(Deserialize, Serialize)]
struct ModelExecution {
    avg_ttft_ms: Option<f64>,
    ttft_available: bool,
    core_model_success_rate: Option<f64>,
    core_model_success_rate_available: bool,
}
#[derive(Deserialize, Serialize)]
struct MemoryMetrics {
    total_pending: u64,
    l2: L2Metrics,
    embeddings: EmbeddingMetrics,
}
#[derive(Deserialize, Serialize)]
struct L2Metrics {
    is_running: bool,
    extract_pending: u64,
    reconcile_pending: u64,
    snapshot_pending: u64,
    total_pending: u64,
}
#[derive(Deserialize, Serialize)]
struct EmbeddingMetrics {
    total_pending: u64,
    l1: EmbeddingLayer,
    l3: EmbeddingLayer,
    l4: EmbeddingLayer,
}
#[derive(Deserialize, Serialize)]
struct EmbeddingLayer {
    pending: u64,
    worker_running: bool,
    vector_enabled: bool,
    async_embeddings: bool,
}
#[derive(Deserialize, Serialize)]
struct SchedulerMetrics {
    enabled_schedule_count: u64,
    running_target_count: u64,
    errored_target_count: u64,
    upcoming_target_count: u64,
    recent_targets: Vec<SchedulerTarget>,
}
#[derive(Deserialize, Serialize)]
struct SchedulerTarget {
    target_type: String,
    target_key: String,
    running: bool,
    last_error: Option<String>,
    next_run_at: Option<f64>,
    updated_at: Option<f64>,
}
