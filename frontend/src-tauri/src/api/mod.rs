mod health;
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
use state::ApiState;

pub fn build_router(state: ApiState) -> Router {
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
        // Fallback: proxy to Python
        .fallback(proxy::proxy_handler)
        .with_state(state)
}
