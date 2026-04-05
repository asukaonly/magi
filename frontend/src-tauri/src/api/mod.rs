mod health;
mod messages;
mod proxy;
mod ready;
mod sessions;
pub mod state;

use axum::Router;
use state::ApiState;

pub fn build_router(state: ApiState) -> Router {
    Router::new()
        .route("/api/health", axum::routing::get(health::health))
        .route("/api/ready", axum::routing::get(ready::ready))
        .route("/api/messages/sessions", axum::routing::get(sessions::list_sessions))
        .route("/api/messages/history", axum::routing::get(messages::message_history))
        .fallback(proxy::proxy_handler)
        .with_state(state)
}
