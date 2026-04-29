use axum::extract::Query;
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};

use super::snapshot::build_trace_snapshot;

#[derive(Deserialize)]
pub struct TraceQuery {
    pub user_id: Option<String>,
    pub session_id: Option<String>,
    pub turn_id: Option<String>,
}

/// Native GET /api/messages/trace handler — reads runtime_trace.db directly.
pub async fn get_trace(Query(params): Query<TraceQuery>) -> Json<Value> {
    let user_id = params.user_id.unwrap_or_else(|| "default_user".to_string());
    let session_id = match &params.session_id {
        Some(s) if !s.is_empty() => s.clone(),
        _ => return Json(json!({"success": false, "trace": null})),
    };
    let turn_id = match &params.turn_id {
        Some(t) if !t.is_empty() => t.clone(),
        _ => return Json(json!({"success": false, "trace": null})),
    };

    let result =
        tokio::task::spawn_blocking(move || build_trace_snapshot(&user_id, &session_id, &turn_id))
            .await
            .unwrap_or_else(|_| json!({"success": false, "trace": null}));
    Json(result)
}
