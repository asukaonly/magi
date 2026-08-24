use serde_json::{json, Value};

use super::storage::{open_tasks_db, row_to_task, TASK_COLUMNS};

pub(super) fn query_tasks(user_id: &str, status: Option<&str>, limit: i64, offset: i64) -> Value {
    let conn = match open_tasks_db() {
        Some(c) => c,
        None => return json!({"tasks": []}),
    };
    let (query, params): (String, Vec<Box<dyn rusqlite::types::ToSql>>) = if let Some(st) = status {
        (
            format!(
                "SELECT {} FROM tasks WHERE user_id = ?1 AND status = ?2 ORDER BY updated_at DESC LIMIT ?3 OFFSET ?4",
                TASK_COLUMNS
            ),
            vec![
                Box::new(user_id.to_string()),
                Box::new(st.to_string()),
                Box::new(limit),
                Box::new(offset),
            ],
        )
    } else {
        (
            format!(
                "SELECT {} FROM tasks WHERE user_id = ?1 ORDER BY updated_at DESC LIMIT ?2 OFFSET ?3",
                TASK_COLUMNS
            ),
            vec![
                Box::new(user_id.to_string()),
                Box::new(limit),
                Box::new(offset),
            ],
        )
    };
    let mut stmt = match conn.prepare(&query) {
        Ok(s) => s,
        Err(_) => return json!({"tasks": []}),
    };
    let param_refs: Vec<&dyn rusqlite::types::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    let tasks: Vec<Value> = stmt
        .query_map(param_refs.as_slice(), row_to_task)
        .ok()
        .map(|iter| iter.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();
    json!({"tasks": tasks})
}

pub(super) fn query_single_task(task_id: &str) -> Option<Value> {
    let conn = open_tasks_db()?;
    let mut stmt = conn
        .prepare(&format!(
            "SELECT {} FROM tasks WHERE task_id = ?1",
            TASK_COLUMNS
        ))
        .ok()?;
    stmt.query_row(rusqlite::params![task_id], row_to_task).ok()
}
