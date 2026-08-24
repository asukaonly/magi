mod health;
mod llm;
mod local_embedding;
mod memory;
mod messages;
mod metrics;
mod private_resources;
mod proxy;
mod ready;
mod schedules;
pub mod security;
mod sessions;
pub mod state;
mod tasks;
mod trace;

use std::path::PathBuf;
use std::sync::Arc;

use axum::extract::DefaultBodyLimit;
use axum::middleware;
use axum::Router;
use state::ApiState;
use tower_http::services::ServeDir;

pub fn build_router(state: ApiState) -> Router {
    // Eagerly warm the sysinfo cache in a background thread so the
    // first /api/metrics/runtime/overview request is fast.
    metrics::warm_sysinfo_cache();

    let cors = state.security.cors_layer();
    let security = Arc::clone(&state.security);

    Router::new()
        // Health / readiness
        .route("/api/health", axum::routing::get(health::health))
        .route("/api/ready", axum::routing::get(ready::ready))
        .route(
            "/api/private-resource-tickets",
            axum::routing::post(private_resources::issue_private_resource_ticket),
        )
        // Chat messages
        .route(
            "/api/messages/sessions",
            axum::routing::get(sessions::list_sessions),
        )
        .route(
            "/api/messages/history",
            axum::routing::get(messages::message_history),
        )
        .route(
            "/api/messages/session/{session_id}/attachments",
            axum::routing::post(proxy::attachment_upload_proxy_handler).layer(
                DefaultBodyLimit::max(messages::MAX_ATTACHMENT_UPLOAD_BODY_BYTES),
            ),
        )
        .route(
            "/api/messages/session/{session_id}/attachments/{attachment_id}/content",
            axum::routing::get(messages::attachment_content),
        )
        .route(
            "/api/messages/session/new",
            axum::routing::post(messages::create_session),
        )
        .route(
            "/api/messages/session/{session_id}/workspace",
            axum::routing::patch(messages::update_session_workspace),
        )
        .route(
            "/api/messages/workspaces/recent",
            axum::routing::get(messages::list_recent_workspaces).post(messages::remember_workspace),
        )
        .route(
            "/api/messages/session/{session_id}/message/{message_id}/label",
            axum::routing::post(messages::set_message_label),
        )
        .route(
            "/api/messages/session/{session_id}/message/{message_id}",
            axum::routing::delete(proxy::proxy_handler),
        )
        .route(
            "/api/messages/session/{session_id}",
            axum::routing::patch(messages::rename_session).delete(proxy::proxy_handler),
        )
        .route("/api/messages/trace", axum::routing::get(trace::get_trace))
        // Tasks
        .route(
            "/api/tasks/{task_id}",
            axum::routing::get(tasks::get_task)
                .patch(tasks::update_task)
                .delete(tasks::delete_task),
        )
        .route(
            "/api/tasks",
            axum::routing::get(tasks::list_tasks).post(tasks::create_task),
        )
        // Schedules
        .route(
            "/api/schedules/activity/{activity_id}/cancel",
            axum::routing::post(schedules::cancel_activity),
        )
        .route(
            "/api/schedules/activity",
            axum::routing::get(schedules::list_activity),
        )
        .route(
            "/api/schedules/executions/recent",
            axum::routing::get(schedules::list_recent_executions),
        )
        .route(
            "/api/schedules/{schedule_id}/executions",
            axum::routing::get(schedules::list_schedule_executions),
        )
        .route(
            "/api/schedules/{schedule_id}",
            axum::routing::get(schedules::get_schedule)
                .patch(schedules::update_schedule)
                .delete(schedules::delete_schedule),
        )
        .route(
            "/api/schedules",
            axum::routing::get(schedules::list_schedules).post(schedules::create_schedule),
        )
        // LLM metrics
        .route(
            "/api/metrics/llm/usage/summary",
            axum::routing::get(metrics::llm_usage_summary),
        )
        .route(
            "/api/metrics/llm/usage/timeseries",
            axum::routing::get(metrics::llm_usage_timeseries),
        )
        .route(
            "/api/metrics/runtime/overview",
            axum::routing::get(metrics::runtime_overview),
        )
        // Memory
        .route(
            "/api/memory/l2/statistics",
            axum::routing::get(memory::get_l2_statistics),
        )
        .route(
            "/api/memory/identity/links",
            axum::routing::get(memory::get_identity_links),
        )
        .route(
            "/api/memory/l1/events",
            axum::routing::get(memory::list_l1_events),
        )
        .route(
            "/api/memory/l2/relations",
            axum::routing::get(memory::list_l2_relations),
        )
        .route(
            "/api/memory/l2/assertions",
            axum::routing::get(memory::list_l2_assertions),
        )
        .route(
            "/api/memory/l2/entities",
            axum::routing::get(memory::list_l2_entities),
        )
        .route(
            "/api/memory/l2/mentions",
            axum::routing::get(memory::list_l2_mentions),
        )
        .route(
            "/api/memory/l2/snapshots",
            axum::routing::get(memory::list_l2_snapshots),
        )
        .route(
            "/api/memory/l2/conflict-rules",
            axum::routing::get(memory::list_l2_conflict_rules),
        )
        .route(
            "/api/memory/l3/summaries",
            axum::routing::get(memory::list_l3_summaries),
        )
        .route(
            "/api/memory/l2/pending",
            axum::routing::get(memory::get_l2_pending),
        )
        .route(
            "/api/memory/background/pending",
            axum::routing::get(memory::get_background_pending),
        )
        .route(
            "/api/memory/procedures",
            axum::routing::get(memory::list_procedures),
        )
        .route(
            "/api/memory/tom/{entity_id}",
            axum::routing::get(memory::get_tom_snapshot),
        )
        // Personality config — proxied to Python backend (registry-based).
        // Personality presets — proxied to Python backend.
        // LLM
        .route(
            "/api/llm/providers/custom-template",
            axum::routing::get(llm::get_custom_template),
        )
        // Local embedding
        .route(
            "/api/local-embedding/discovered",
            axum::routing::get(local_embedding::discover_external_models),
        )
        // Static avatar files — served directly, bypassing IPC proxy
        .nest_service(
            "/static/avatars",
            ServeDir::new(
                state
                    .builtin_avatar_dir
                    .clone()
                    .unwrap_or_else(|| PathBuf::from("/nonexistent")),
            ),
        )
        .nest_service(
            "/static/user-avatars",
            ServeDir::new(
                state
                    .user_avatar_dir
                    .clone()
                    .unwrap_or_else(|| PathBuf::from("/nonexistent")),
            ),
        )
        // Fallback: proxy to Python
        .fallback(proxy::proxy_handler)
        .layer(middleware::from_fn(move |request, next| {
            let security = Arc::clone(&security);
            async move { security::enforce_gateway_access(security, request, next).await }
        }))
        .layer(cors)
        .with_state(state)
}
