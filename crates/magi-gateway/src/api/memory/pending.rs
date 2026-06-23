use axum::Json;
use serde_json::{json, Value};

use crate::db;

use super::read_l2_projection_backlog;

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
    let backlog = db::open_readonly(&db::memory_db_path())
        .map(|conn| read_l2_projection_backlog(&conn))
        .unwrap_or_default();

    json!({
        "is_running": backlog.running > 0,
        "extract_pending": backlog.pending_work(),
        "reconcile_pending": 0,
        "snapshot_pending": 0,
        "projection_pending": backlog.pending,
        "projection_queued": backlog.queued,
        "projection_running": backlog.running,
        "projection_claimed": backlog.claimed(),
        "projection_failed": backlog.failed,
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

#[cfg(test)]
mod tests {
    use super::{build_background_pending, build_l2_pending};
    use crate::db;
    use rusqlite::Connection;
    use std::path::PathBuf;
    use std::sync::MutexGuard;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct IsolatedMagiBase {
        previous_base_dir: Option<PathBuf>,
        root: PathBuf,
        _lock: MutexGuard<'static, ()>,
    }

    impl Drop for IsolatedMagiBase {
        fn drop(&mut self) {
            db::set_magi_base_dir_override_for_tests(self.previous_base_dir.take());
            let _ = std::fs::remove_dir_all(&self.root);
        }
    }

    fn isolated_magi_base(label: &str) -> IsolatedMagiBase {
        let lock = db::magi_base_dir_override_test_lock();
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "magi-gateway-pending-{label}-{}-{nonce}",
            std::process::id()
        ));
        let magi_base = root.join(".magi");
        std::fs::create_dir_all(magi_base.join("data").join("memory")).expect("create memory dir");
        let previous_base_dir = db::set_magi_base_dir_override_for_tests(Some(magi_base));
        IsolatedMagiBase {
            previous_base_dir,
            root,
            _lock: lock,
        }
    }

    fn seed_memory_databases(statuses: &[&str]) {
        let memory_conn = Connection::open(db::memory_db_path()).expect("open memory db");
        memory_conn
            .execute_batch(
                "CREATE TABLE l2_projection_jobs(status TEXT NOT NULL);
                 CREATE TABLE summaries(embedding_status TEXT);
                 CREATE TABLE procedural_skills(embedding_status TEXT);",
            )
            .expect("create memory tables");
        for status in statuses {
            memory_conn
                .execute(
                    "INSERT INTO l2_projection_jobs(status) VALUES (?1)",
                    [status],
                )
                .expect("insert projection job");
        }

        let l1_conn = Connection::open(db::l1_events_db_path()).expect("open l1 db");
        l1_conn
            .execute_batch("CREATE TABLE fact_events(embedding_status TEXT);")
            .expect("create l1 tables");
    }

    #[test]
    fn l2_pending_counts_queued_and_running_projection_jobs_as_claimed() {
        let _base = isolated_magi_base("queued-running-l2");
        seed_memory_databases(&[
            "pending", "queued", "queued", "running", "running", "running",
        ]);

        let pending = build_l2_pending();

        assert_eq!(pending["extract_pending"], 6);
        assert_eq!(pending["projection_pending"], 1);
        assert_eq!(pending["projection_queued"], 2);
        assert_eq!(pending["projection_running"], 3);
        assert_eq!(pending["projection_claimed"], 5);
    }

    #[test]
    fn background_pending_is_not_idle_when_l2_jobs_are_running() {
        let _base = isolated_magi_base("running-background");
        seed_memory_databases(&["running"]);

        let pending = build_background_pending();

        assert_eq!(pending["l2"]["extract_pending"], 1);
        assert_eq!(pending["l2"]["projection_running"], 1);
        assert_eq!(pending["all_idle"], false);
    }
}
