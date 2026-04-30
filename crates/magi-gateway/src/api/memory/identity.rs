use axum::Json;
use serde_json::{json, Value};

// ---------------------------------------------------------------------------
// Identity links
// ---------------------------------------------------------------------------

/// GET /api/memory/identity/links — identity mappings.
pub async fn get_identity_links() -> Json<Value> {
    Json(json!({
        "canonical_self_id": "user:self",
        "links": [],
    }))
}
