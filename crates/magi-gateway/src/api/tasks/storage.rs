use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};

use crate::db;

pub(super) const TASK_COLUMNS: &str = "task_id, title, description, status, priority, tags_json, \
    due_date, created_by, user_id, session_id, linked_turn_id, created_at, updated_at";

pub(super) fn open_tasks_db() -> Option<Connection> {
    let path = db::tasks_db_path();
    if !path.exists() {
        return None;
    }
    Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY).ok()
}

pub(super) fn row_to_task(row: &rusqlite::Row) -> rusqlite::Result<Value> {
    let tags_json: String = row
        .get::<_, Option<String>>(5)?
        .unwrap_or_else(|| "[]".into());
    let tags: Value = serde_json::from_str(&tags_json).unwrap_or(json!([]));
    Ok(json!({
        "task_id": row.get::<_, String>(0)?,
        "title": row.get::<_, String>(1)?,
        "description": row.get::<_, String>(2)?,
        "status": row.get::<_, String>(3)?,
        "priority": row.get::<_, String>(4)?,
        "tags": tags,
        "due_date": row.get::<_, Option<f64>>(6)?,
        "created_by": row.get::<_, String>(7)?,
        "user_id": row.get::<_, String>(8)?,
        "session_id": row.get::<_, Option<String>>(9)?,
        "linked_turn_id": row.get::<_, Option<String>>(10)?,
        "created_at": row.get::<_, f64>(11)?,
        "updated_at": row.get::<_, f64>(12)?,
    }))
}
