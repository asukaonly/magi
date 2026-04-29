use axum::Json;
use serde_json::{json, Value};

use crate::db;

// ---------------------------------------------------------------------------
// Unified memory statistics
// ---------------------------------------------------------------------------

/// GET /api/memory/statistics — per-layer memory statistics (L0–L4).
pub async fn get_memory_statistics() -> Json<Value> {
    let result = tokio::task::spawn_blocking(build_memory_statistics)
        .await
        .unwrap_or_else(|_| json!({}));
    Json(result)
}

fn build_memory_statistics() -> Value {
    let mut stats = json!({});

    let mut l1_count: i64 = 0;
    let mut l2_rel_count: i64 = 0;
    let mut l2_tom_count: i64 = 0;
    let mut l3_count: i64 = 0;
    let mut l4_count: i64 = 0;
    let mut open_cb_count: i64 = 0;
    let mut pending_assertions: i64 = 0;

    let memory_db = db::memory_db_path();
    let l1_db = db::l1_events_db_path();

    // L0 — from memory.db checkpoint tables
    if let Some(conn) = db::open_readonly(&memory_db) {
        let active_sessions = db::count_rows(
            &conn,
            "SELECT COUNT(*) FROM l0_sessions WHERE status = 'active'",
            &[],
        );
        let total_goals = db::count_rows(&conn, "SELECT COUNT(*) FROM l0_goal_stack", &[]);
        let total_entities = db::count_rows(&conn, "SELECT COUNT(*) FROM l0_active_entities", &[]);
        let total_tactics = db::count_rows(&conn, "SELECT COUNT(*) FROM l0_temporary_tactics", &[]);
        stats["l0"] = json!({
            "active_sessions": active_sessions,
            "total_goals": total_goals,
            "total_entities": total_entities,
            "total_tactics": total_tactics,
        });

        // L2
        l2_rel_count = db::count_rows(
            &conn,
            "SELECT COUNT(*) FROM knowledge_graph WHERE status = 'active'",
            &[],
        );
        l2_tom_count = db::count_rows(&conn, "SELECT COUNT(*) FROM tom_trait_assertions", &[]);
        stats["l2"] = json!({
            "relation_count": l2_rel_count,
            "assertion_count": l2_tom_count,
        });

        // Pending assertions (tentative / contradicted)
        pending_assertions = db::count_rows(
            &conn,
            "SELECT COUNT(*) FROM tom_trait_assertions \
             WHERE validation_state IN ('tentative', 'contradicted') AND status = 'active'",
            &[],
        );

        // L3
        l3_count = db::count_rows(&conn, "SELECT COUNT(*) FROM summaries", &[]);
        stats["l3"] = json!({ "summary_count": l3_count });

        // L4
        l4_count = db::count_rows(&conn, "SELECT COUNT(*) FROM procedural_skills", &[]);
        open_cb_count = db::count_rows(
            &conn,
            "SELECT COUNT(*) FROM procedural_skills WHERE circuit_breaker_state = 'open'",
            &[],
        );
        stats["l4"] = json!({ "skill_count": l4_count, "open_circuit_breakers": open_cb_count });
    }

    // L1 — from l1_events.db
    // Avoid full-table-scan on large databases: COUNT(*) without WHERE is
    // O(1) in SQLite, then subtract the (typically tiny) deleted set.
    if let Some(conn) = db::open_readonly(&l1_db) {
        let total = db::count_rows(&conn, "SELECT COUNT(*) FROM fact_events", &[]);
        let deleted = db::count_rows(
            &conn,
            "SELECT COUNT(*) FROM fact_events WHERE deleted_at IS NOT NULL",
            &[],
        );
        l1_count = total - deleted;
        stats["l1"] = json!({ "event_count": l1_count });
    }

    // Aggregate totals
    let total_memories = l1_count + l2_rel_count + l2_tom_count + l3_count + l4_count;
    stats["total_memories"] = json!(total_memories);

    // Disk usage: sum sizes of the two db files
    let mut disk_usage_bytes: u64 = 0;
    for path in [&memory_db, &l1_db] {
        if let Ok(meta) = std::fs::metadata(path) {
            disk_usage_bytes += meta.len();
        }
    }
    stats["disk_usage_bytes"] = json!(disk_usage_bytes);

    // Attention items
    stats["attention"] = json!({
        "pending_assertions": pending_assertions,
        "open_circuit_breakers": open_cb_count,
    });

    stats
}
