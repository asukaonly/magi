use axum::Json;
use serde_json::{json, Value};

use crate::db;

// ---------------------------------------------------------------------------
// L2 Pending
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/pending — queue backlog stats.
pub async fn get_l2_pending() -> Json<Value> {
    let result = tokio::task::spawn_blocking(build_l2_pending)
        .await
        .unwrap_or_else(|_| json!({}));
    Json(result)
}

fn build_l2_pending() -> Value {
    let (pending, claimed, failed) = match db::open_readonly(&db::memory_db_path()) {
        Some(conn) => {
            let rows = db::query_to_json_array(
                &conn,
                "SELECT status, COUNT(*) AS cnt FROM l2_projection_jobs GROUP BY status",
                &[],
            );
            let mut p: i64 = 0;
            let mut c: i64 = 0;
            let mut f: i64 = 0;
            for row in &rows {
                let s = row.get("status").and_then(|v| v.as_str()).unwrap_or("");
                let n = row.get("cnt").and_then(|v| v.as_i64()).unwrap_or(0);
                match s {
                    "pending" => p = n,
                    "claimed" => c = n,
                    "failed" => f = n,
                    _ => {}
                }
            }
            (p, c, f)
        }
        None => (0, 0, 0),
    };

    json!({
        "is_running": false,
        "extract_pending": pending + claimed,
        "reconcile_pending": 0,
        "snapshot_pending": 0,
        "projection_pending": pending,
        "projection_claimed": claimed,
        "projection_failed": failed,
    })
}

// ---------------------------------------------------------------------------
// Background Pending
// ---------------------------------------------------------------------------

/// GET /api/memory/background/pending — multi-layer pending counts.
pub async fn get_background_pending() -> Json<Value> {
    let result = tokio::task::spawn_blocking(build_background_pending)
        .await
        .unwrap_or_else(|_| json!({}));
    Json(result)
}

fn build_background_pending() -> Value {
    let l2 = build_l2_pending();

    // Embedding pending counts read from the DB.
    let l1_pending = build_embedding_pending_from_db(&db::l1_events_db_path(), "fact_events");
    let l3_pending = build_embedding_pending_from_db(&db::memory_db_path(), "summaries");
    let l4_pending = build_embedding_pending_from_db(&db::memory_db_path(), "procedural_skills");

    let all_idle = l2
        .get("extract_pending")
        .and_then(|v| v.as_i64())
        .unwrap_or(0)
        == 0
        && l2
            .get("reconcile_pending")
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
            == 0
        && l2
            .get("snapshot_pending")
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
            == 0
        && l1_pending
            .get("pending")
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
            == 0
        && l3_pending
            .get("pending")
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
            == 0
        && l4_pending
            .get("pending")
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
            == 0;

    json!({
        "l2": l2,
        "l1_embeddings": l1_pending,
        "l3_embeddings": l3_pending,
        "l4_embeddings": l4_pending,
        "all_idle": all_idle,
    })
}

/// Count rows with embedding_status = 'pending' in a given table.
fn build_embedding_pending_from_db(db_path: &std::path::Path, table: &str) -> Value {
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
