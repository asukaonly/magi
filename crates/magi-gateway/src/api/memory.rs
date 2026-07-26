mod identity;
mod l1;
mod l2;
mod l3;
mod l4;
mod pending;
mod query;

use serde_json::{json, Value};

pub use identity::get_identity_links;
pub use l1::list_l1_events;
pub use l2::{
    get_l2_statistics, get_tom_snapshot, list_l2_assertions, list_l2_conflict_rules,
    list_l2_entities, list_l2_mentions, list_l2_relations, list_l2_snapshots,
};
pub use l3::list_l3_summaries;
pub use l4::list_procedures;
pub use pending::{get_background_pending, get_l2_pending};

#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct L2ProjectionBacklog {
    pub pending: i64,
    pub queued: i64,
    pub running: i64,
    pub completed: i64,
    pub failed: i64,
}

impl L2ProjectionBacklog {
    pub(crate) fn claimed(self) -> i64 {
        self.queued + self.running
    }

    pub(crate) fn pending_work(self) -> i64 {
        self.pending + self.claimed()
    }
}

pub(crate) fn read_l2_projection_backlog(conn: &rusqlite::Connection) -> L2ProjectionBacklog {
    let rows = crate::db::query_to_json_array(
        conn,
        "SELECT status, COUNT(*) AS cnt FROM l2_projection_jobs GROUP BY status",
        &[],
    );
    let mut backlog = L2ProjectionBacklog::default();
    for row in &rows {
        let status = row.get("status").and_then(|v| v.as_str()).unwrap_or("");
        let count = row.get("cnt").and_then(|v| v.as_i64()).unwrap_or(0);
        match status {
            "pending" => backlog.pending = count,
            "queued" => backlog.queued = count,
            "running" => backlog.running = count,
            "completed" => backlog.completed = count,
            "failed" => backlog.failed = count,
            _ => {}
        }
    }
    backlog
}

pub(crate) fn l2_projection_backlog_json(backlog: L2ProjectionBacklog) -> Value {
    json!({
        "pending": backlog.pending,
        "queued": backlog.queued,
        "running": backlog.running,
        "claimed": backlog.claimed(),
        "completed": backlog.completed,
        "failed": backlog.failed,
    })
}
