use serde_json::Value;

use crate::db;

use super::read::query_single_task;
use super::types::{TaskCreateBody, TaskUpdateBody};

pub(super) fn insert_task(user_id: &str, body: TaskCreateBody) -> Option<Value> {
    let conn = open_tasks_db_rw()?;
    let task_id = format!("task_{}", &uuid::Uuid::new_v4().to_string()[..12]);
    let now = now_seconds()?;
    let description = body.description.unwrap_or_default();
    let priority = body.priority.unwrap_or_else(|| "medium".to_string());
    let tags = body.tags.unwrap_or_default();
    let tags_json = serde_json::to_string(&tags).unwrap_or_else(|_| "[]".to_string());

    conn.execute(
        "INSERT INTO tasks (task_id, title, description, status, priority, tags_json, \
         due_date, created_by, user_id, session_id, linked_turn_id, created_at, updated_at) \
         VALUES (?1, ?2, ?3, 'open', ?4, ?5, ?6, 'user', ?7, NULL, ?8, ?9, ?10)",
        rusqlite::params![
            task_id,
            body.title,
            description,
            priority,
            tags_json,
            body.due_date,
            user_id,
            body.linked_turn_id,
            now,
            now,
        ],
    )
    .ok()?;
    query_single_task(&task_id)
}

pub(super) fn patch_task(task_id: &str, body: TaskUpdateBody) -> Option<Value> {
    let conn = open_tasks_db_rw()?;
    let now = now_seconds()?;

    let mut sets = Vec::new();
    let mut params: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
    let mut idx = 1;

    macro_rules! add_field {
        ($field:expr, $col:expr) => {
            if let Some(val) = $field {
                sets.push(format!("{} = ?{}", $col, idx));
                params.push(Box::new(val));
                idx += 1;
            }
        };
    }

    add_field!(body.title, "title");
    add_field!(body.description, "description");
    add_field!(body.status, "status");
    add_field!(body.priority, "priority");
    if let Some(tags) = body.tags {
        let tags_json = serde_json::to_string(&tags).unwrap_or_else(|_| "[]".to_string());
        sets.push(format!("tags_json = ?{}", idx));
        params.push(Box::new(tags_json));
        idx += 1;
    }
    add_field!(body.due_date, "due_date");
    add_field!(body.linked_turn_id, "linked_turn_id");

    if sets.is_empty() {
        return query_single_task(task_id);
    }

    sets.push(format!("updated_at = ?{}", idx));
    params.push(Box::new(now));
    idx += 1;

    let sql = format!(
        "UPDATE tasks SET {} WHERE task_id = ?{}",
        sets.join(", "),
        idx
    );
    params.push(Box::new(task_id.to_string()));

    let param_refs: Vec<&dyn rusqlite::types::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    conn.execute(&sql, param_refs.as_slice()).ok()?;
    query_single_task(task_id)
}

pub(super) fn remove_task(task_id: &str) -> bool {
    let conn = match open_tasks_db_rw() {
        Some(c) => c,
        None => return false,
    };
    conn.execute(
        "DELETE FROM tasks WHERE task_id = ?1",
        rusqlite::params![task_id],
    )
    .map(|n| n > 0)
    .unwrap_or(false)
}

fn now_seconds() -> Option<f64> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()
        .map(|duration| duration.as_secs_f64())
}

fn open_tasks_db_rw() -> Option<rusqlite::Connection> {
    db::open_readwrite(&db::tasks_db_path())
}
