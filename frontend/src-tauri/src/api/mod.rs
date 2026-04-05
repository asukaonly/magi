mod health;
mod memory;
mod messages;
mod metrics;
mod proxy;
mod ready;
mod schedules;
mod sessions;
pub mod state;
mod tasks;
mod trace;

use axum::Router;
use tower_http::cors::{Any, CorsLayer};
use state::ApiState;

pub fn build_router(state: ApiState) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    Router::new()
        // Health / readiness
        .route("/api/health", axum::routing::get(health::health))
        .route("/api/ready", axum::routing::get(ready::ready))
        // Chat messages
        .route("/api/messages/sessions", axum::routing::get(sessions::list_sessions))
        .route("/api/messages/history", axum::routing::get(messages::message_history))
        .route("/api/messages/trace", axum::routing::get(trace::get_trace))
        // Tasks
        .route("/api/tasks/orchestration/{orchestration_id}", axum::routing::get(tasks::list_tasks_by_orchestration))
        .route("/api/tasks/{task_id}", axum::routing::get(tasks::get_task))
        .route("/api/tasks", axum::routing::get(tasks::list_tasks))
        // Schedules
        .route("/api/schedules/executions/recent", axum::routing::get(schedules::list_recent_executions))
        .route("/api/schedules/{schedule_id}/executions", axum::routing::get(schedules::list_schedule_executions))
        .route("/api/schedules/{schedule_id}", axum::routing::get(schedules::get_schedule))
        .route("/api/schedules", axum::routing::get(schedules::list_schedules))
        // LLM metrics
        .route("/api/metrics/llm/usage/summary", axum::routing::get(metrics::llm_usage_summary))
        .route("/api/metrics/llm/usage/timeseries", axum::routing::get(metrics::llm_usage_timeseries))
        // Memory
        .route("/api/memory/l1/events", axum::routing::get(memory::list_l1_events))
        .route("/api/memory/l2/relations", axum::routing::get(memory::list_l2_relations))
        .route("/api/memory/l2/assertions", axum::routing::get(memory::list_l2_assertions))
        .route("/api/memory/l2/entities", axum::routing::get(memory::list_l2_entities))
        .route("/api/memory/l2/mentions", axum::routing::get(memory::list_l2_mentions))
        .route("/api/memory/l2/snapshots", axum::routing::get(memory::list_l2_snapshots))
        .route("/api/memory/l2/conflict-rules", axum::routing::get(memory::list_l2_conflict_rules))
        .route("/api/memory/l3/summaries", axum::routing::get(memory::list_l3_summaries))
        // Fallback: proxy to Python
        .fallback(proxy::proxy_handler)
        .layer(cors)
        .with_state(state)
}
