mod health;
mod proxy;
pub mod state;

use axum::Router;
use state::ApiState;

pub fn build_router(state: ApiState) -> Router {
    Router::new()
        .route("/api/health", axum::routing::get(health::health))
        .fallback(proxy::proxy_handler)
        .with_state(state)
}
